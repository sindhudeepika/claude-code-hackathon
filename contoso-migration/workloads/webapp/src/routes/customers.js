'use strict';

const express = require('express');
const { query } = require('../db');

const router = express.Router();

function redactPii(customer) {
  return {
    ...customer,
    email: customer.email ? `${customer.email[0]}***@***.***` : null,
    phone: customer.phone ? `***${customer.phone.slice(-4)}` : null,
  };
}

router.get('/', async (req, res) => {
  const page = Math.max(1, parseInt(req.query.page || '1', 10));
  const limit = Math.min(100, Math.max(1, parseInt(req.query.limit || '20', 10)));
  const offset = (page - 1) * limit;

  const result = await query(
    `SELECT c.id, c.first_name, c.last_name, c.email, c.phone, c.created_at,
            COUNT(a.id) AS account_count
     FROM customers c
     LEFT JOIN accounts a ON a.customer_id = c.id
     GROUP BY c.id
     ORDER BY c.created_at DESC
     LIMIT $1 OFFSET $2`,
    [limit, offset]
  );

  const countResult = await query('SELECT COUNT(*) AS total FROM customers');
  const total = parseInt(countResult.rows[0].total, 10);

  res.json({
    data: result.rows.map(redactPii),
    pagination: { page, limit, total, pages: Math.ceil(total / limit) },
  });
});

router.get('/:id', async (req, res) => {
  const result = await query(
    `SELECT c.id, c.first_name, c.last_name, c.email, c.phone, c.uk_postcode, c.created_at,
            json_agg(json_build_object(
              'id', a.id,
              'type', a.account_type,
              'balance', a.balance
            ) ORDER BY a.created_at) FILTER (WHERE a.id IS NOT NULL) AS accounts
     FROM customers c
     LEFT JOIN accounts a ON a.customer_id = c.id
     WHERE c.id = $1
     GROUP BY c.id`,
    [req.params.id]
  );

  if (result.rows.length === 0) {
    return res.status(404).json({ error: 'Customer not found' });
  }

  const customer = result.rows[0];
  const internalScope = req.headers['x-pii-scope'] === 'internal';

  res.json(internalScope ? customer : redactPii(customer));
});

module.exports = router;
