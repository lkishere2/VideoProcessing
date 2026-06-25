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
      summaryData: null,
      errorMsg: ''
    }));
    setVideos(prev => [...prev, ...newVideos]);
  };

  const updateVideoState = (id, updates) => {
    setVideos(prev => prev.map(vid => vid.id === id ? { ...vid, ...updates } : vid));
  };

  const processSingleVideo = async (vid) => {
    if (['complete', 'error'].includes(vid.status)) return;

    try {
      updateVideoState(vid.id, { status: 'extracting' });
      
      const formData = new FormData();
      formData.append('file', vid.file);
      formData.append('fps', 1);
      
      const extractRes = await axios.post(`${API_BASE}/process_video`, formData);
      if (extractRes.data.error) throw new Error(extractRes.data.error);

      const { video_id, frames } = extractRes.data;
      updateVideoState(vid.id, { status: 'showing_frames', frames: frames });
      await new Promise(resolve => setTimeout(resolve, 1500));

      updateVideoState(vid.id, { status: 'summarizing' });
      const summarizeRes = await axios.post(`${API_BASE}/summarize`, {
        video_id: video_id,
        frames: frames
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
    await Promise.all(videos.map(vid => processSingleVideo(vid)));
    setGlobalStatus('complete');
  };

  const clearQueue = () => {
    setVideos([]);
    setGlobalStatus('idle');
  };

  return (
    <VideoContext.Provider value={{ videos, globalStatus, addFilesToQueue, processAllVideos, clearQueue }}>
      {children}
    </VideoContext.Provider>
  );
};
