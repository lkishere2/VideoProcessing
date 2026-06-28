import { createContext, useState, useContext } from 'react';
import axios from 'axios';

const VideoContext = createContext();

export const useVideoContext = () => useContext(VideoContext);

const API_BASE = `http://${window.location.hostname}:8000/api`;

export const VideoProvider = ({ children }) => {
  const [videos, setVideos] = useState([]);
  const [globalStatus, setGlobalStatus] = useState('idle');

  const addFilesToQueue = (filesArray) => {
    const newVideos = filesArray.map(file => ({
      id: Date.now().toString(36) + Math.random().toString(36).substring(2),
      file: file,
      status: 'pending',
      frames: [],
      voiceSegments: [],
      summaryData: null,
      errorMsg: '',
      metrics: {}
    }));
    setVideos(prev => [...prev, ...newVideos]);
  };

  const addUrlToQueue = (url) => {
    const newVideo = {
      id: Date.now().toString(36) + Math.random().toString(36).substring(2),
      url: url,
      file: { name: url }, // Mock file object for UI rendering
      status: 'pending',
      frames: [],
      voiceSegments: [],
      summaryData: null,
      errorMsg: '',
      metrics: {}
    };
    setVideos(prev => [...prev, newVideo]);
  };

  const updateVideoState = (id, updates) => {
    setVideos(prev => prev.map(vid => vid.id === id ? { ...vid, ...updates } : vid));
  };

  const processSingleVideo = async (vid) => {
    if (['complete', 'error'].includes(vid.status)) return;

    try {
      updateVideoState(vid.id, { status: 'extracting' });
      
      const formData = new FormData();
      if (vid.url) {
        formData.append('url', vid.url);
      } else {
        formData.append('file', vid.file);
      }
      formData.append('fps', 1);
      
      const extractRes = await axios.post(`${API_BASE}/process_video`, formData);
      if (extractRes.data.error) throw new Error(extractRes.data.error);

      // voice_segments holds the audio-pipeline's detected chunks:
      // [{ start, end, text, emotion }, ...] - captured here and passed
      // through to /api/summarize so the enriched transcript actually
      // reaches Nova, and kept in state so the UI can show what audio
      // chunks were detected.
      const { video_id, video_title, frames, voice_segments, metrics } = extractRes.data;
      updateVideoState(vid.id, {
        status: 'showing_frames',
        frames: frames,
        voiceSegments: voice_segments || [],
        metrics: metrics || {},
        file: { name: video_title || vid.file.name }
      });
      await new Promise(resolve => setTimeout(resolve, 1500));

      updateVideoState(vid.id, { status: 'summarizing' });
      const summarizeRes = await axios.post(`${API_BASE}/summarize`, {
        video_id: video_id,
        frames: frames,
        voice_segments: voice_segments || [],
      });
      
      updateVideoState(vid.id, { status: 'complete', summaryData: summarizeRes.data });

    } catch (err) {
      console.error(err);
      const errorMessage = err.response?.data?.detail || err.message || 'An error occurred';
      updateVideoState(vid.id, { status: 'error', errorMsg: errorMessage });
    }
  };

  const processAllVideos = async () => {
    if (videos.length === 0) return;
    setGlobalStatus('processing');

    const CONCURRENCY_LIMIT = 10;
    const queue = [...videos];

    // Worker loops that pull from the same shared queue
    const worker = async () => {
      while (queue.length > 0) {
        const vid = queue.shift();
        if (vid) {
          await processSingleVideo(vid);
        }
      }
    };

    // Spin up workers up to the concurrency limit
    const workers = Array(Math.min(CONCURRENCY_LIMIT, queue.length))
      .fill(null)
      .map(worker);

    await Promise.all(workers);
    setGlobalStatus('complete');
  };

  const clearQueue = () => {
    setVideos([]);
    setGlobalStatus('idle');
  };

  return (
    <VideoContext.Provider value={{ videos, globalStatus, addFilesToQueue, addUrlToQueue, processAllVideos, clearQueue }}>
      {children}
    </VideoContext.Provider>
  );
};