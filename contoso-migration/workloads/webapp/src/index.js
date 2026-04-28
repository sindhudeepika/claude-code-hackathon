'use strict';

require('dotenv').config();

const express = require('express');
const morgan = require('morgan');
const helmet = require('helmet');
const config = require('./config');

const healthRouter = require('./routes/health');
const customersRouter = require('./routes/customers');
const transactionsRouter = require('./routes/transactions');

const app = express();

app.use(helmet());
app.use(express.json());

// Log to stdout only (never to a file in cloud deployments — see config.js discovery finding #2)
if (!config.logFile) {
  app.use(morgan('combined'));
} else {
  const fs = require('fs');
  const path = require('path');
  fs.mkdirSync(path.dirname(config.logFile), { recursive: true });
  app.use(morgan('combined', { stream: fs.createWriteStream(config.logFile, { flags: 'a' }) }));
}

app.use('/health', healthRouter);
app.use('/api/customers', customersRouter);
app.use('/api', transactionsRouter);

app.use((req, res) => {
  res.status(404).json({ error: 'Not found' });
});

app.use((err, req, res, _next) => {
  console.error('Unhandled error', { message: err.message, stack: err.stack });
  res.status(500).json({ error: 'Internal server error' });
});

const server = app.listen(config.port, () => {
  console.log(JSON.stringify({
    event: 'server_started',
    port: config.port,
    env: config.nodeEnv,
    timestamp: new Date().toISOString(),
  }));
});

process.on('SIGTERM', () => {
  server.close(() => {
    console.log(JSON.stringify({ event: 'server_stopped', timestamp: new Date().toISOString() }));
    process.exit(0);
  });
});

module.exports = app;
