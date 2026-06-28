import { useRef, useState } from 'react';
import { useVideoContext } from '../context/VideoContext';

export default function UploadSection() {
  const { addFilesToQueue, addUrlToQueue } = useVideoContext();
  const fileInputRef = useRef(null);
  const [urlInput, setUrlInput] = useState('');

  const handleFileSelect = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      addFilesToQueue(Array.from(e.target.files));
    }
  };

  const handleDragOver = (e) => e.preventDefault();
  const handleDrop = (e) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      addFilesToQueue(Array.from(e.dataTransfer.files));
    }
  };

  const handleUrlSubmit = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (urlInput.trim()) {
      addUrlToQueue(urlInput.trim());
      setUrlInput('');
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div 
        className="upload-section" 
        onClick={() => fileInputRef.current.click()}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
      >
        <div className="upload-icon">📁</div>
        <h2>Drag & Drop multiple .mp4 files here</h2>
        <p className="text-muted" style={{marginTop: '10px'}}>Click to browse</p>
        <input 
          type="file" 
          accept=".mp4,video/mp4" 
          multiple
          ref={fileInputRef} 
          style={{ display: 'none' }} 
          onChange={handleFileSelect}
        />
      </div>

      <div 
        className="url-section" 
        onClick={(e) => e.stopPropagation()} 
        style={{
          display: 'flex',
          gap: '10px',
          alignItems: 'center',
          padding: '15px',
          background: 'rgba(255,255,255,0.02)',
          borderRadius: '12px',
          border: '1px solid var(--border-color)'
        }}
      >
        <input 
          type="text" 
          placeholder="Or paste a video URL (TikTok, YouTube Shorts, Reels...)" 
          value={urlInput}
          onChange={(e) => setUrlInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleUrlSubmit(e)}
          style={{
            flex: 1,
            padding: '10px 14px',
            background: 'rgba(0,0,0,0.2)',
            border: '1px solid var(--border-color)',
            borderRadius: '6px',
            color: 'var(--text-main)',
            fontSize: '0.9rem'
          }}
        />
        <button 
          className="btn btn-primary"
          onClick={handleUrlSubmit}
          style={{ whiteSpace: 'nowrap' }}
        >
          Add URL
        </button>
      </div>
    </div>
  );
}
