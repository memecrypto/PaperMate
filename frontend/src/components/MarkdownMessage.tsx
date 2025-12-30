import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import CodeBlock from './shared/CodeBlock'

interface MarkdownMessageProps {
  content: string
}

export default function MarkdownMessage({ content }: MarkdownMessageProps) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        code: (props) => <CodeBlock {...props} />
      }}
    >
      {content}
    </ReactMarkdown>
  )
}
