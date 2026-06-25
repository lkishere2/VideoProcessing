import { useState } from 'react';
import ImageItem from './ImageItem';
import ImageModal from './ImageModal';
import JSZip from 'jszip';
import { saveAs } from 'file-saver';

export default function ImageSection({ frames, filename }) {
  const [selectedIndex, setSelectedIndex] = useState(null);

  if (!frames || frames.length === 0) return null;

  const handleDownloadZip = async () => {
    const zip = new JSZip();
    frames.forEach((frameData, index) => {
      const base64Data = frameData.base64.split(",")[1];
      zip.file(`frame_${index}.jpg`, base64Data, {base64: true});
    });

    const safeFilename = filename.replace(/[^a-zA-Z0-9.\- ]/g, "").trim();
    const content = await zip.generateAsync({type: "blob"});
    saveAs(content, `frames_${safeFilename}.zip`);
  };

  return (
    <div className="glass-panel" style={{marginTop: '20px'}}>
      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '15px'}}>
        <h3 style={{margin: 0, color: 'var(--text-main)'}}>Extracted Frames ({frames.length})</h3>
        <button className="btn btn-secondary" onClick={handleDownloadZip}>
          Download Frames (ZIP)
        </button>
      </div>
      
      <div className="frames-grid">
        {frames.map((frameData, i) => (
          <ImageItem key={i} index={i} frameData={frameData} onClick={setSelectedIndex} />
        ))}
      </div>

      {/* Lightbox Modal */}
      {selectedIndex !== null && (
        <ImageModal 
          frames={frames} 
          selectedIndex={selectedIndex} 
          setSelectedIndex={setSelectedIndex} 
          onClose={() => setSelectedIndex(null)} 
        />
      )}
    </div>
  );
}
