#!/usr/bin/env node
// t1k-origin: kit=theonekit-core | repo=The1Studio/theonekit-core | module=null | protected=true
'use strict';

/**
 * Transcript Parser - Extract agent/todo state from session JSONL
 * T1K-native — no external dependencies
 */

const fs = require('fs');
const readline = require('readline');

function isNativeTaskTodo(todo) { return Boolean(todo && todo._source === 'native_task'); }

function normalizeTodo(todo) {
  if (!todo || typeof todo !== 'object') return null;
  const normalized = { content: todo.content ?? '', status: todo.status ?? 'pending', activeForm: todo.activeForm ?? null };
  if (todo.id != null) normalized.id = todo.id;
  return normalized;
}

function extractTaskIdFromValue(value) {
  if (value == null) return null;
  if (typeof value === 'string') {
    try { const parsed = JSON.parse(value); return extractTaskIdFromValue(parsed); } catch {}
    const match = value.match(/["']?task[_-]?id["']?\s*[:=]\s*["']([^"']+)["']/i);
    return match?.[1] || null;
  }
  if (typeof value !== 'object') return null;
  if (value.taskId != null) return String(value.taskId);
  if (value.task_id != null) return String(value.task_id);
  if (Array.isArray(value)) {
    for (const item of value) { const id = extractTaskIdFromValue(item); if (id) return id; }
    return null;
  }
  for (const v of Object.values(value)) { const id = extractTaskIdFromValue(v); if (id) return id; }
  return null;
}

async function parseTranscript(transcriptPath) {
  const result = { tools: [], agents: [], todos: [], sessionStart: null };
  if (!transcriptPath || !fs.existsSync(transcriptPath)) return result;

  const toolMap = new Map();
  const agentMap = new Map();
  let latestTodos = [];

  try {
    const rl = readline.createInterface({ input: fs.createReadStream(transcriptPath), crlfDelay: Infinity });
    for await (const line of rl) {
      if (!line.trim()) continue;
      try { processEntry(JSON.parse(line), toolMap, agentMap, latestTodos, result); } catch {}
    }
  } catch {}

  result.tools = Array.from(toolMap.values()).slice(-20);
  result.agents = Array.from(agentMap.values()).slice(-10);
  result.todos = latestTodos.map(normalizeTodo).filter(Boolean);
  return result;
}

function processEntry(entry, toolMap, agentMap, latestTodos, result) {
  const timestamp = entry.timestamp ? new Date(entry.timestamp) : new Date();
  if (!result.sessionStart && entry.timestamp) result.sessionStart = timestamp;

  const content = entry.message?.content;
  if (!content || !Array.isArray(content)) return;

  for (const block of content) {
    if (block.type === 'tool_use' && block.id && block.name) {
      if (block.name === 'Task') {
        agentMap.set(block.id, { id: block.id, type: block.input?.subagent_type ?? 'unknown', model: block.input?.model ?? null, description: block.input?.description ?? null, status: 'running', startTime: timestamp, endTime: null });
      } else if (block.name === 'TodoWrite' && Array.isArray(block.input?.todos)) {
        latestTodos.length = 0;
        latestTodos.push(...block.input.todos.map(t => ({ ...t, _source: 'legacy_todowrite' })));
      } else if (block.name === 'TaskCreate' && block.input?.subject) {
        latestTodos.push({ id: block.id, content: block.input.subject, status: 'pending', activeForm: block.input.activeForm || null, _source: 'native_task', _toolUseId: block.id });
      } else if (block.name === 'TaskUpdate' && block.input?.taskId && block.input?.status) {
        const taskId = String(block.input.taskId);
        const nativeTodos = latestTodos.filter(isNativeTaskTodo);
        let task = nativeTodos.find(t => String(t.id) === taskId);
        if (!task && /^\d+$/.test(taskId)) { const idx = Number(taskId) - 1; if (idx >= 0 && idx < nativeTodos.length) task = nativeTodos[idx]; }
        if (task) { task.status = block.input.status; if ('activeForm' in block.input) task.activeForm = block.input.activeForm || null; }
      } else {
        toolMap.set(block.id, { id: block.id, name: block.name, status: 'running', startTime: timestamp, endTime: null });
      }
    }
    if (block.type === 'tool_result' && block.tool_use_id) {
      const tool = toolMap.get(block.tool_use_id);
      if (tool) { tool.status = block.is_error ? 'error' : 'completed'; tool.endTime = timestamp; }
      const agent = agentMap.get(block.tool_use_id);
      if (agent) { agent.status = 'completed'; agent.endTime = timestamp; }
      const createdTask = latestTodos.find(t => isNativeTaskTodo(t) && t._toolUseId === block.tool_use_id);
      if (createdTask) { const id = extractTaskIdFromValue(block.content); if (id) createdTask.id = id; }
    }
  }
}

module.exports = { parseTranscript, processEntry };
