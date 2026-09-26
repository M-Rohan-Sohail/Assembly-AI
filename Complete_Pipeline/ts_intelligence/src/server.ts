import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import { Person2Pipeline } from './pipeline';

dotenv.config({ path: '../../.env' }); // Pick up GROQ_API_KEY from root .env

const app = express();
app.use(cors());
app.use(express.json());

const pipeline = new Person2Pipeline();

app.post('/repair', async (req, res) => {
  try {
    const event = req.body;
    console.log(`[P2] Received transcript: "${event.text}"`);
    const result = await pipeline.repair(event);
    console.log(`[P2] Repaired text: "${result.repairedText}"`);
    res.json(result);
  } catch (error) {
    console.error("[P2] Repair error:", error);
    res.status(500).json({ error: String(error) });
  }
});

const PORT = 8787;
app.listen(PORT, () => {
  console.log(`[P2] Person 2 Intelligence server running on port ${PORT}`);
});
