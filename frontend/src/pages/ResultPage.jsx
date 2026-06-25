import { useParams, useNavigate } from 'react-router-dom';
import { useVideoContext } from '../context/VideoContext';
import SummarySection from '../components/SummarySection';
import ImageSection from '../components/ImageSection';

export default function ResultPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { videos } = useVideoContext();

  const video = videos.find(v => v.id === id);

  if (!video) {
    return (
      <div className="dashboard">
        <div className="glass-panel">
          <h2>Video Not Found</h2>
          <button className="btn" onClick={() => navigate('/')}>Back to Home</button>
        </div>
      </div>
    );
  }

  const { file, status, frames, summaryData, errorMsg } = video;

  // Calculate total execution time for Vision AI across all frames
  const totalExecutionTime = frames.reduce((acc, f) => acc + (f.execution_time || 0), 0);

  return (
    <div className="dashboard">
      <div className="header" style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
        <div style={{textAlign: 'left'}}>
          <h2 style={{margin:0, color: 'var(--text-main)', fontSize: '2rem'}}>{file.name}</h2>
          <p>Analysis Results</p>
        </div>
        <button className="btn btn-secondary" onClick={() => navigate('/')}>&larr; Back to Dashboard</button>
      </div>

      <div className="glass-panel video-card" style={{marginBottom: '20px'}}>
        <div className="video-card-header">
          <h3>Status Overview</h3>
          <span className={`status-badge status-${status}`}>
            {status.replace('_', ' ').toUpperCase()}
          </span>
        </div>

        {status !== 'pending' && (
          <div className="workflow-steps mini-steps">
            <Step
              label="Local AI Analysis"
              active={status === 'extracting'}
              completed={['showing_frames', 'summarizing', 'complete'].includes(status)}
            />
            <Step
              label="Claude Aggregation"
              active={status === 'summarizing'}
              completed={status === 'complete'}
            />
          </div>
        )}

        {status === 'error' && (
          <div className="error-msg" style={{marginTop: '15px'}}>
            Error: {errorMsg}
          </div>
        )}

        {status === 'complete' && <SummarySection summaryData={summaryData} totalExecutionTime={totalExecutionTime} />}
      </div>

      <ImageSection frames={frames} filename={file.name} />
    </div>
  );
}

function Step({ label, active, completed }) {
  let className = "step";
  if (active) className += " active";
  if (completed) className += " completed";

  return (
    <div className={className}>
      <div className="step-icon">
        {completed ? '✓' : (active ? '●' : '')}
      </div>
      <div>{label}</div>
    </div>
  );
}
