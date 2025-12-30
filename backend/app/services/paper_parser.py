import uuid
import asyncio
import httpx
import zipfile
import io
import json
import re
from pathlib import Path
from sqlalchemy import select, delete
from app.core.config import get_settings
from app.core.database import async_session_maker
from app.models import Paper, PaperSection, PaperFormula, PaperAsset
from app.services.storage import StorageService

settings = get_settings()

CLOUD_API_BASE = f"{settings.mineru_api_url.rstrip('/')}/api/v4"


async def parse_paper_task(paper_id: uuid.UUID, storage_key: str | None) -> None:
    """Background task to parse a PDF using MinerU API."""
    async with async_session_maker() as db:
        try:
            paper = await db.get(Paper, paper_id)
            if not paper:
                return

            paper.status = "parsing"
            await db.commit()

            if not storage_key:
                paper.status = "failed"
                await db.commit()
                return

            storage = StorageService()
            file_path = await storage.get_file_path(storage_key)

            if settings.mineru_use_cloud:
                parsed_data = await call_mineru_cloud_api(file_path, paper_id)
            else:
                parsed_data = await call_mineru_local_api(file_path, paper_id)

            # Paper may have been deleted while parsing; stop gracefully.
            exists = await db.scalar(select(Paper.id).where(Paper.id == paper_id))
            if not exists:
                return

            paper.title = parsed_data.get("title", paper.title or "Untitled")
            paper.abstract = parsed_data.get("abstract")
            paper.authors = parsed_data.get("authors")

            # Replace previous parse results to avoid duplicates on re-parse.
            await db.execute(delete(PaperSection).where(PaperSection.paper_id == paper_id))
            await db.execute(delete(PaperFormula).where(PaperFormula.paper_id == paper_id))
            await db.execute(delete(PaperAsset).where(PaperAsset.paper_id == paper_id))

            for section_data in parsed_data.get("sections", []):
                section = PaperSection(
                    paper_id=paper_id,
                    section_type=section_data.get("type"),
                    title=section_data.get("title"),
                    page_start=section_data.get("page_start"),
                    page_end=section_data.get("page_end"),
                    content_text=section_data.get("text"),
                    content_md=section_data.get("markdown")
                )
                db.add(section)

            for formula_data in parsed_data.get("formulas", []):
                formula = PaperFormula(
                    paper_id=paper_id,
                    latex=formula_data.get("latex"),
                    page=formula_data.get("page"),
                    bbox=formula_data.get("bbox")
                )
                db.add(formula)

            for asset_data in parsed_data.get("assets", []):
                asset = PaperAsset(
                    paper_id=paper_id,
                    type=asset_data.get("type", "figure"),
                    label=asset_data.get("label"),
                    caption=asset_data.get("caption"),
                    page=asset_data.get("page")
                )
                db.add(asset)

            paper.status = "ready"
            await db.commit()

        except Exception:
            paper = await db.get(Paper, paper_id)
            if paper:
                paper.status = "failed"
                await db.commit()
            raise


def _cloud_headers() -> dict[str, str]:
    """Build headers for MinerU cloud API."""
    if not settings.mineru_api_key:
        raise ValueError("MINERU_API_KEY is required for cloud API")
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.mineru_api_key}"
    }


async def call_mineru_cloud_api(file_path: Path, paper_id: uuid.UUID) -> dict:
    """
    Call MinerU Cloud API (https://mineru.net).

    Flow:
    1. Request upload URL via /file-urls/batch
    2. PUT file to the upload URL
    3. Poll /extract-results/batch/{batch_id} until done
    4. Download and parse the result zip
    """
    async with httpx.AsyncClient(timeout=600.0) as client:
        # Step 1: Get upload URL
        batch_resp = await client.post(
            f"{CLOUD_API_BASE}/file-urls/batch",
            headers=_cloud_headers(),
            json={
                "files": [{"name": file_path.name}],
                "model_version": settings.mineru_model_version
            }
        )

        if batch_resp.status_code != 200:
            try:
                error_data = batch_resp.json()
                if error_data.get("msgCode") == "A0202":
                    raise Exception("MinerU API Key 无效或已过期，请在设置中更新 API Key")
                raise Exception(f"MinerU batch API error: {error_data.get('msg', batch_resp.text)}")
            except Exception as e:
                if "API Key" in str(e):
                    raise
                raise Exception(f"MinerU batch API error: {batch_resp.status_code} - {batch_resp.text}")

        batch_data = batch_resp.json()
        if batch_data.get("code") != 0:
            raise Exception(f"MinerU batch API error: {batch_data.get('msg')}")

        batch_id = batch_data["data"]["batch_id"]
        upload_url = batch_data["data"]["file_urls"][0]

        # Step 2: Upload file
        with open(file_path, "rb") as f:
            upload_resp = await client.put(upload_url, content=f.read())

        if upload_resp.status_code != 200:
            raise Exception(f"File upload failed: {upload_resp.status_code}")

        # Step 3: Poll for result
        result_data = await _poll_batch_result(client, batch_id)

        # Step 4: Download and parse zip
        zip_url = (
            result_data.get("full_zip_url")
            or result_data.get("zip_url")
            or result_data.get("download_url")
        )
        if not zip_url:
            raise Exception("No result zip URL in response")

        return await _download_and_parse_zip(client, zip_url, paper_id)


async def _poll_batch_result(client: httpx.AsyncClient, batch_id: str, max_attempts: int = 120) -> dict:
    """Poll batch result until done or failed."""
    headers = _cloud_headers()
    headers.pop("Content-Type", None)

    for attempt in range(max_attempts):
        resp = await client.get(
            f"{CLOUD_API_BASE}/extract-results/batch/{batch_id}",
            headers=headers
        )

        if resp.status_code != 200:
            raise Exception(f"Poll API error: {resp.status_code}")

        data = resp.json()
        if data.get("code") != 0:
            raise Exception(f"Poll API error: {data.get('msg')}")

        results = data.get("data", {}).get("extract_result", [])
        if not results:
            await asyncio.sleep(5)
            continue

        result = results[0]
        state = result.get("state")

        if state == "done":
            return result
        elif state == "failed":
            raise Exception(f"MinerU parsing failed: {result.get('err_msg')}")
        elif state in ("pending", "running", "waiting-file", "converting"):
            await asyncio.sleep(5)
        else:
            await asyncio.sleep(5)

    raise Exception("MinerU parsing timeout")


async def _download_and_parse_zip(client: httpx.AsyncClient, zip_url: str, paper_id: uuid.UUID) -> dict:
    """Download result zip, extract markdown and images, and rewrite links."""
    resp = await client.get(zip_url, follow_redirects=True)
    if resp.status_code != 200:
        raise Exception(f"Failed to download result: {resp.status_code}")

    markdown_content = ""
    content_list = []
    image_files: dict[str, bytes] = {}

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        md_candidates = []
        for info in zf.infolist():
            name = info.filename
            if name.endswith(".md"):
                md_candidates.append((info.file_size, name))
            elif name.endswith("content_list.json"):
                content_list = json.loads(zf.read(name).decode("utf-8"))
            else:
                lower = name.lower()
                if lower.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")):
                    image_files[name] = zf.read(name)

        if md_candidates:
            _, md_name = max(md_candidates)
            markdown_content = zf.read(md_name).decode("utf-8")

    # Persist images locally and rewrite markdown links to our API.
    asset_storage_keys: dict[str, str] = {}
    if image_files:
        storage = StorageService()
        image_url_map: dict[str, str] = {}
        for original_name, data in image_files.items():
            safe_name = Path(original_name).name
            key = f"paper_assets/{paper_id}/{safe_name}"
            await storage.save_file_with_key(data, key)
            url = f"/api/v1/papers/files/{key}"
            image_url_map[original_name] = url
            image_url_map[safe_name] = url
            asset_storage_keys[safe_name] = key

        def _rewrite_md_image(match: re.Match[str]) -> str:
            prefix, url, suffix = match.groups()
            cleaned = url.strip().strip("'\"").strip("<>")
            if cleaned.startswith("http://") or cleaned.startswith("https://"):
                return match.group(0)
            parts = re.split(r"\s+", cleaned, maxsplit=1)
            path_part = parts[0]
            title_part = f" {parts[1]}" if len(parts) > 1 else ""

            lookup = path_part.lstrip("./")
            new_url = image_url_map.get(lookup) or image_url_map.get(Path(lookup).name)
            if not new_url:
                return match.group(0)
            return f"{prefix}{new_url}{title_part}{suffix}"

        markdown_content = re.sub(r"(!\[[^\]]*\]\()([^)]+)(\))", _rewrite_md_image, markdown_content)

        def _rewrite_html_image(match: re.Match[str]) -> str:
            prefix, url, suffix = match.groups()
            cleaned = url.strip().strip("'\"")
            if cleaned.startswith("http://") or cleaned.startswith("https://"):
                return match.group(0)
            lookup = cleaned.lstrip("./")
            new_url = image_url_map.get(lookup) or image_url_map.get(Path(lookup).name)
            if not new_url:
                return match.group(0)
            return f"{prefix}{new_url}{suffix}"

        markdown_content = re.sub(
            r'(<img[^>]+src=["\'])([^"\']+)(["\'])',
            _rewrite_html_image,
            markdown_content,
            flags=re.IGNORECASE,
        )

    return parse_mineru_response({
        "markdown": markdown_content,
        "content_list": content_list,
        "asset_storage_keys": asset_storage_keys
    })


async def call_mineru_local_api(file_path: Path, paper_id: uuid.UUID) -> dict:
    """Call locally deployed MinerU API."""
    async with httpx.AsyncClient(timeout=600.0) as client:
        with open(file_path, "rb") as f:
            files = {"file": (file_path.name, f, "application/pdf")}

            response = await client.post(
                f"{settings.mineru_api_url}/file/parse",
                files=files,
                data={
                    "parse_method": "auto",
                    "output_format": "markdown"
                },
                headers=settings.mineru_headers()
            )

        if response.status_code != 200:
            raise Exception(f"MinerU API error: {response.status_code} - {response.text}")

        return parse_mineru_response(response.json())


def parse_mineru_response(result: dict) -> dict:
    """Parse MinerU API response into our internal format."""
    parsed = {
        "title": "",
        "abstract": "",
        "authors": "",
        "sections": [],
        "formulas": [],
        "assets": []
    }

    content_list = result.get("content_list", [])
    if not content_list:
        content_list = result.get("data", {}).get("content_list", [])

    markdown_content = result.get("markdown", "") or result.get("md", "")

    if markdown_content:
        lines = markdown_content.split("\n")
        for line in lines:
            if line.startswith("# ") and not parsed["title"]:
                parsed["title"] = line[2:].strip()
                break

    section_types = {
        "abstract": "abstract",
        "introduction": "introduction",
        "related work": "related_work",
        "background": "background",
        "method": "methodology",
        "methodology": "methodology",
        "experiment": "experiments",
        "result": "results",
        "discussion": "discussion",
        "conclusion": "conclusion",
        "reference": "references"
    }

    # Always extract formulas/assets from content_list when available.
    for item in content_list:
        item_type = item.get("type", "text")
        text = item.get("text", "") or item.get("md", "")
        page = item.get("page_idx", item.get("page"))

        if item_type == "equation" or item.get("latex"):
            parsed["formulas"].append({
                "latex": item.get("latex", text),
                "page": page,
                "bbox": item.get("bbox")
            })
            continue

        if item_type in ("image", "figure", "table"):
            parsed["assets"].append({
                "type": "figure" if item_type != "table" else "table",
                "label": item.get("label"),
                "caption": item.get("caption", text[:200] if text else None),
                "page": page
            })
            continue

        if item_type == "text" and text and not parsed["abstract"]:
            text_lower = text.lower().strip()
            first_line = text.split("\n")[0].strip().lower()
            if first_line.startswith("abstract") or section_types.get(first_line) == "abstract":
                abstract_text = text
                if "abstract" in text_lower[:50]:
                    abstract_text = text[text_lower.find("abstract") + 8:].strip()
                parsed["abstract"] = abstract_text[:2000]

    # Prefer MinerU-provided markdown for display to preserve formatting.
    if markdown_content:
        if not parsed["abstract"]:
            m = re.search(r"(?im)^#+\s*abstract\s*$\n(.*?)(?=^#+\s|\Z)", markdown_content)
            if m:
                parsed["abstract"] = m.group(1).strip()[:2000]

        parsed["sections"] = [{
            "type": "full_text",
            "title": "Full Document",
            "text": markdown_content,
            "markdown": markdown_content
        }]
        return parsed

    # Fallback: no markdown, build a single text section.
    if content_list:
        full_text = "\n\n".join(
            (item.get("md") or item.get("text") or "")
            for item in content_list
            if item.get("type", "text") == "text"
        )
        if full_text.strip():
            parsed["sections"] = [{
                "type": "full_text",
                "title": parsed["title"] or "Full Document",
                "text": full_text,
                "markdown": full_text
            }]

    return parsed
