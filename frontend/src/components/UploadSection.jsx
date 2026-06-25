import { useRef } from 'react';
import { useVideoContext } from '../context/VideoContext';

export default function UploadSection() {
  const { addFilesToQueue } = useVideoContext();
  const fileInputRef = useRef(null);

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

  return (
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
  );
}
