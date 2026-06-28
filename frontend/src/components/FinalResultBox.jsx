import { createPortal } from 'react-dom';
import JSZip from 'jszip';
import { saveAs } from 'file-saver';
import { useState } from 'react';

function formatTime(seconds) {
  const m = Math.floor(seconds / 60).toString().padStart(2, '0');
  const s = (Math.floor(seconds % 60)).toString().padStart(2, '0');
  return `${m}:${s}`;
}

export default function FinalResultBox({ videos, onClose }) {
  const [isZipping, setIsZipping] = useState(false);

  // Only include videos that completed successfully
  const completedVideos = videos.filter(vid => vid.status === 'complete' && vid.summaryData);

  if (completedVideos.length === 0) return null;

  const totalTime = completedVideos.reduce((acc, vid) => acc + 
    (vid.summaryData.llm_inference_time_sec || 0) + 
    (vid.metrics?.frame_processing_sec || 0) + 
    (vid.metrics?.audio_processing_sec || 0)
  , 0);
  const totalCost = completedVideos.reduce((acc, vid) => acc + (vid.summaryData.cost || 0), 0);
  const totalTokens = completedVideos.reduce((acc, vid) => 
    acc + (vid.summaryData.input_tokens || 0) + (vid.summaryData.output_tokens || 0)
  , 0);

  const handleDownloadAll = async () => {
    setIsZipping(true);
    try {
      const zip = new JSZip();

      for (const vid of completedVideos) {
        const safeVideoName = vid.file.name.replace(/[^a-zA-Z0-9.\- ]/g, "").trim();
        // Create a subfolder for each video
        const videoFolder = zip.folder(safeVideoName);

        // 1. Add the video file itself
        videoFolder.file(vid.file.name, vid.file);

        // 2. Add summary.md
        let summaryContent = `# Summary for ${vid.file.name}\n\n`;
        if (vid.summaryData && vid.summaryData.summary) {
          summaryContent += `${vid.summaryData.summary}\n`;
        }
        videoFolder.file('summary.md', summaryContent);

        // 3. Add frames folder with images and voice
        const framesFolder = videoFolder.folder('frames');
        if (vid.frames) {
          vid.frames.forEach((frameData, index) => {
            if (frameData.base64) {
              const base64Data = frameData.base64.split(",")[1];
              framesFolder.file(`frame_${index}.jpg`, base64Data, {base64: true});
            }
            if (frameData.voice_text) {
              framesFolder.file(`frame_${index}_voice.txt`, frameData.voice_text);
            }
          });
        }

        // 4. Add the audio-pipeline transcript (significant chunks, with
        // tone tags) as its own file, separate from the per-frame voice
        // text above - this is the same data shown in the Audio Chunks
        // panel on the result page.
        if (vid.voiceSegments && vid.voiceSegments.length > 0) {
          const sorted = [...vid.voiceSegments].sort((a, b) => a.start - b.start);
          const transcriptLines = sorted.map(seg =>
            `[${formatTime(seg.start)} - ${formatTime(seg.end)}, ${seg.emotion || 'Neutral'}] ${seg.text || '(no speech detected)'}`
          );
          videoFolder.file('transcript.txt', transcriptLines.join('\n'));
        }
      }

      const content = await zip.generateAsync({type: "blob"});
      saveAs(content, "all_video_results.zip");
    } catch (err) {
      console.error("Error creating ZIP:", err);
      alert("Failed to create ZIP file.");
    } finally {
      setIsZipping(false);
    }
  };

  return createPortal(
    <div className="modal-overlay" onClick={onClose} style={{ zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div className="glass-panel" onClick={e => e.stopPropagation()} style={{ padding: '30px', maxWidth: '500px', width: '90%', textAlign: 'center', position: 'relative' }}>
        <button className="modal-close" onClick={onClose} style={{ top: '15px', right: '15px' }}>&times;</button>
        <h2 style={{ marginBottom: '20px', color: 'var(--accent-color)' }}>🎉 Processing Complete!</h2>
        <p style={{ marginBottom: '30px', color: 'var(--text-muted)' }}>
          Successfully analyzed {completedVideos.length} video{completedVideos.length !== 1 ? 's' : ''}. Here is the total breakdown:
        </p>
        
        <div className="stats" style={{ gridTemplateColumns: '1fr', gap: '15px' }}>
          <div className="stat-item">
            <span className="stat-label">Total Processing Time</span>
            <span className="stat-value" style={{ fontSize: '1.5rem', color: '#6ee7b7' }}>{totalTime.toFixed(2)}s</span>
          </div>
          <div className="stat-item">
            <span className="stat-label">Total API Tokens Used</span>
            <span className="stat-value" style={{ fontSize: '1.5rem', color: '#93c5fd' }}>{totalTokens.toLocaleString()}</span>
          </div>
          <div className="stat-item">
            <span className="stat-label">Total Cost</span>
            <span className="stat-value" style={{ fontSize: '1.5rem', color: '#fca5a5' }}>${totalCost.toFixed(4)}</span>
          </div>
        </div>
        
        <button 
          className="btn btn-primary" 
          onClick={handleDownloadAll} 
          disabled={isZipping}
          style={{ marginTop: '20px', width: '100%' }}
        >
          {isZipping ? 'Generating ZIP...' : 'Download All Results (ZIP)'}
        </button>
        <button className="btn" onClick={onClose} style={{ marginTop: '10px', width: '100%', background: 'var(--surface-color)', border: '1px solid var(--border-color)', color: 'var(--text-main)' }}>
          Dismiss
        </button>
      </div>
    </div>,
    document.body
  );
}