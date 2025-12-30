import React, { useMemo, useState } from 'react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { Copy, Check } from 'lucide-react'

interface CodeBlockProps {
  inline?: boolean
  className?: string
  children?: React.ReactNode
}

export default function CodeBlock({ inline, className, children }: CodeBlockProps) {
  const code = useMemo(() => String(children ?? '').replace(/\n$/, ''), [children])
  const match = /language-(\w+)/.exec(className || '')
  const language = match?.[1]
  const [copied, setCopied] = useState(false)

  if (inline || !language) {
    return (
      <code className="rounded bg-gray-100 px-1.5 py-0.5 text-sm text-gray-800 font-mono">
        {children}
      </code>
    )
  }

  const handleCopy = async () => {
    await navigator.clipboard.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="relative my-3 group">
      <div className="flex items-center justify-between px-4 py-2 bg-gray-900 text-gray-400 text-xs rounded-t-lg border-b border-gray-700">
        <span className="uppercase font-semibold tracking-wider">{language}</span>
        <button
          type="button"
          onClick={handleCopy}
          className="flex items-center gap-1 hover:text-white transition-colors"
          title="Copy code"
        >
          {copied ? <Check className="w-3.5 h-3.5 text-green-500" /> : <Copy className="w-3.5 h-3.5" />}
          <span>{copied ? 'Copied!' : 'Copy'}</span>
        </button>
      </div>
      <SyntaxHighlighter
        language={language}
        style={vscDarkPlus}
        showLineNumbers
        wrapLongLines
        customStyle={{
          margin: 0,
          borderRadius: '0 0 0.5rem 0.5rem',
          fontSize: '0.85rem',
          lineHeight: '1.5',
        }}
      >
        {code}
      </SyntaxHighlighter>
    </div>
  )
}
