import ReactMarkdown from 'react-markdown';

export default function SummarySection({ summaryData, totalExecutionTime, metrics }) {
  if (!summaryData) return null;

  return (
    <div className="summary-box" style={{marginTop: '20px'}}>
      <h3>Final Summary</h3>
      <div className="markdown-content">
        <ReactMarkdown>{summaryData.summary}</ReactMarkdown>
      </div>

      <h4 style={{marginTop: '20px', borderBottom: '1px solid #E5E7EB', paddingBottom: '10px', color: 'var(--text-main)'}}>Performance Metrics</h4>
      <div className="stats">
        <div className="stat-item">
          <span className="stat-label">Total Frames</span>
          <span className="stat-value">{summaryData.frames_count}</span>
        </div>
        <div className="stat-item">
          <span className="stat-label">Frame Extraction</span>
          <span className="stat-value">{metrics?.frame_processing_sec?.toFixed(2) || '0.00'}s</span>
        </div>
        <div className="stat-item">
          <span className="stat-label">Audio Extraction</span>
          <span className="stat-value">{metrics?.audio_processing_sec?.toFixed(2) || '0.00'}s</span>
        </div>
        <div className="stat-item">
          <span className="stat-label">LLM Inference</span>
          <span className="stat-value">{summaryData.llm_inference_time_sec?.toFixed(2) || '0.00'}s</span>
        </div>
        <div className="stat-item">
          <span className="stat-label">Tokens (In / Out)</span>
          <span className="stat-value">{summaryData.input_tokens} / {summaryData.output_tokens}</span>
        </div>
        <div className="stat-item">
          <span className="stat-label">Total Tokens</span>
          <span className="stat-value">{summaryData.input_tokens + summaryData.output_tokens}</span>
        </div>
        <div className="stat-item">
          <span className="stat-label">Total Cost</span>
          <span className="stat-value">${summaryData.cost.toFixed(4)}</span>
        </div>
      </div>
    </div>
  );
}