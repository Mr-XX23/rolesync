import { createSlice } from '@reduxjs/toolkit';
import type { PayloadAction } from '@reduxjs/toolkit';

export interface TaskItem {
  id: string;
  name: string;
  status: 'Running' | 'Scheduled' | 'Completed' | 'Failed';
  type: string;
  schedule: string;
  lastRun: string;
  clients?: string[];
  instruction?: string;
  groundingData?: string[];
}

interface TaskState {
  tasks: TaskItem[];
  isModalOpen: boolean;
}

const initialState: TaskState = {
  tasks: [
    {
      id: '1',
      name: 'Salesforce Contact Delta Extraction',
      status: 'Running',
      type: 'Sync Data',
      schedule: 'Every 2 hours',
      lastRun: '1 hour ago',
      clients: ['Acme Corp'],
      instruction: 'Synchronize active lead segments with central data warehouse.',
      groundingData: ['Client-Specific Knowledge Base'],
    },
    {
      id: '2',
      name: 'Vector Database Re-indexing Shards',
      status: 'Scheduled',
      type: 'Model Tuning',
      schedule: 'Daily at 02:00 AM',
      lastRun: '22 hours ago',
      clients: ['Global Corp'],
      instruction: 'Re-index pgvector partitions for high-throughput semantic queries.',
      groundingData: ['Proprietary Industry Benchmarks'],
    },
    {
      id: '3',
      name: 'Ingest Competitor Pricing Portal',
      status: 'Completed',
      type: 'Scraper Ingestion',
      schedule: 'Weekly on Mondays',
      lastRun: '1 day ago',
      clients: ['Acme Corp', 'Delta LLC'],
      instruction: 'Track competitor pricing matrix changes and flag anomalies.',
      groundingData: ['Historical Client Interaction Data'],
    },
  ],
  isModalOpen: false,
};

const taskSlice = createSlice({
  name: 'task',
  initialState,
  reducers: {
    addTask: (state, action: PayloadAction<Omit<TaskItem, 'id' | 'status' | 'lastRun'>>) => {
      const newId = (state.tasks.length + 1).toString();
      state.tasks.unshift({
        ...action.payload,
        id: newId,
        status: 'Running', // Newly deployed agents run immediately
        lastRun: 'Just now',
      });
    },
    removeTask: (state, action: PayloadAction<string>) => {
      state.tasks = state.tasks.filter((task) => task.id !== action.payload);
    },
    setModalOpen: (state, action: PayloadAction<boolean>) => {
      state.isModalOpen = action.payload;
    },
    runTaskNow: (state, action: PayloadAction<string>) => {
      const taskIndex = state.tasks.findIndex((task) => task.id === action.payload);
      if (taskIndex !== -1) {
        state.tasks[taskIndex].status = 'Running';
        state.tasks[taskIndex].lastRun = 'Just now';
      }
    },
  },
});

export const { addTask, removeTask, setModalOpen, runTaskNow } = taskSlice.actions;
export default taskSlice.reducer;
