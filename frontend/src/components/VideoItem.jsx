import { useNavigate } from 'react-router-dom';

export default function VideoItem({ video }) {
  const navigate = useNavigate();
  const { id, file, status, errorMsg } = video;

  return (
    <div 
      className="glass-panel video-card clickable" 
      onClick={() => navigate(`/result/${id}`)}
      style={{cursor: 'pointer'}}
    >
      <div className="video-card-header">
        <h3>{file.name}</h3>
        <span className={`status-badge status-${status}`}>
          {status.replace('_', ' ').toUpperCase()}
        </span>
      </div>
      {status === 'error' && (
        <div className="error-msg">Error: {errorMsg}</div>
      )}
      <div style={{marginTop: '10px', fontSize: '0.8rem', color: 'var(--text-muted)'}}>
        Click to view detailed AI analysis & frames &rarr;
      </div>
    </div>
  );
}
