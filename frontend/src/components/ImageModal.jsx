import { useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';

function formatTime(seconds) {
  const m = Math.floor(seconds / 60).toString().padStart(2, '0');
  const s = (Math.floor(seconds % 60)).toString().padStart(2, '0');
  return `${m}:${s}`;
}

export default function ImageModal({ frames, selectedIndex, setSelectedIndex, onClose }) {
  
  const handlePrev = useCallback((e) => {
    if (e) e.stopPropagation();
    if (selectedIndex > 0) setSelectedIndex(selectedIndex - 1);
  }, [selectedIndex, setSelectedIndex]);
  
  const handleNext = useCallback((e) => {
    if (e) e.stopPropagation();
    if (selectedIndex < frames.length - 1) setSelectedIndex(selectedIndex + 1);
  }, [selectedIndex, frames.length, setSelectedIndex]);

  useEffect(() => {
    document.body.style.overflow = 'hidden';
    
    const handleKeyDown = (e) => {
      if (e.key === 'ArrowLeft') {
        handlePrev();
      } else if (e.key === 'ArrowRight') {
        handleNext();
      } else if (e.key === 'Escape') {
        onClose();
      }
    };
    
    window.addEventListener('keydown', handleKeyDown);
    
    return () => {
      document.body.style.overflow = 'unset';
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [handlePrev, handleNext, onClose]);

  if (selectedIndex === null || !frames || !frames[selectedIndex]) return null;
  const image = frames[selectedIndex];

  return createPortal(
    <div className="modal-overlay" onClick={onClose}>
      {selectedIndex > 0 && (
        <button className="nav-arrow nav-left" onClick={handlePrev}>&lsaquo;</button>
      )}
      
      <div className="modal-content" onClick={e => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>&times;</button>
        <img src={image.base64} alt="Full resolution frame" className="modal-image" />
        <div className="modal-caption" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div>{selectedIndex + 1} / {frames.length} | Timestamp: {formatTime(image.t1)} - {formatTime(image.t2)}</div>
          {image.voice_text && (
            <div style={{color: '#aaa', fontSize: '0.9rem', fontStyle: 'italic'}}>
              🎙️ "{image.voice_text}"
            </div>
          )}
          {image.audio && (
            <div style={{ marginTop: '4px', width: '100%', display: 'flex', justifyContent: 'center' }}>
              <audio 
                controls 
                src={image.audio} 
                style={{ 
                  width: '100%', 
                  height: '32px',
                  filter: 'invert(0.9) hue-rotate(180deg) opacity(0.85)'
                }} 
              />
            </div>
          )}
        </div>
      </div>
      
      {selectedIndex < frames.length - 1 && (
        <button className="nav-arrow nav-right" onClick={handleNext}>&rsaquo;</button>
      )}
    </div>,
    document.body
  );
}
