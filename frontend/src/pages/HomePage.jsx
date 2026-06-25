import UploadSection from '../components/UploadSection';
import VideoItem from '../components/VideoItem';
import { useVideoContext } from '../context/VideoContext';

export default function HomePage() {
  const { videos, globalStatus, processAllVideos, clearQueue } = useVideoContext();

  return (
    <div className="dashboard">
      <div className="header">
        <h1>Video Insight Engine</h1>
        <p>AI-powered multi-video analysis</p>
      </div>

      <div className="glass-panel">
        <UploadSection />

        {videos.length > 0 && (
          <div className="queue-actions" style={{marginTop: '20px'}}>
            <button 
              className="btn" 
              onClick={processAllVideos}
              disabled={globalStatus === 'processing'}
            >
              {globalStatus === 'processing' ? 'Processing Videos...' : 'Process All Videos'}
            </button>
            <button 
              className="btn btn-secondary" 
              onClick={clearQueue}
              disabled={globalStatus === 'processing'}
              style={{ marginLeft: '10px' }}
            >
              Clear Queue
            </button>
          </div>
        )}
      </div>

      {videos.length > 0 && (
        <div className="videos-grid" style={{marginTop: '20px'}}>
          {videos.map(vid => (
            <VideoItem key={vid.id} video={vid} />
          ))}
        </div>
      )}
    </div>
  );
}
