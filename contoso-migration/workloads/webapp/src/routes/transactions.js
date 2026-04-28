'use strict';

const express = require('express');
const { query } = require('../db');

const router = express.Router();

router.get('/customers/:id/transactions', async (req, res) => {
  const page = Math.max(1, parseInt(req.query.page || '1', 10));
  const limit = Math.min(200, Math.max(1, parseInt(req.query.limit || '50', 10)));
  const offset = (page - 1) * limit;

  const customerCheck = await query('SELECT id FROM customers WHERE id = $1', [req.params.id]);
  if (customerCheck.rows.length === 0) {
    return res.status(404).json({ error: 'Customer not found' });
  }

  const result = await query(
    `SELECT t.id, t.amount, t.description, t.transaction_date, t.status,
            a.account_type, t.external_ref
     FROM transactions t
     JOIN accounts a ON a.id = t.account_id
     WHERE a.customer_id = $1
     ORDER BY t.transaction_date DESC
     LIMIT $2 OFFSET $3`,
    [req.params.id, limit, offset]
  );

  const countResult = await query(
    `SELECT COUNT(*) AS total FROM transactions t
     JOIN accounts a ON a.id = t.account_id
     WHERE a.customer_id = $1`,
    [req.params.id]
  );

  res.json({
    data: result.rows,
    pagination: {
      page,
      limit,
      total: parseInt(countResult.rows[0].total, 10),
      pages: Math.ceil(parseInt(countResult.rows[0].total, 10) / limit),
    },
  });
});

module.exports = router;
