'use strict';

const express = require('express');
const { healthCheck } = require('../db');

const router = express.Router();

router.get('/', async (req, res) => {
  try {
    const dbOk = await healthCheck();
    res.status(200).json({
      status: 'ok',
      timestamp: new Date().toISOString(),
      version: process.env.npm_package_version || '1.0.0',
      checks: {
        database: dbOk ? 'ok' : 'degraded',
      },
    });
  } catch (err) {
    res.status(503).json({
      status: 'unhealthy',
      timestamp: new Date().toISOString(),
      checks: {
        database: 'failed',
      },
      error: err.message,
    });
  }
});

module.exports = router;
