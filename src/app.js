require('dotenv').config();
const express = require('express');
const routes = require('./routes/api');
const timeoutMiddleware = require('./middleware/timeout');

const app = express();
const PORT = process.env.PORT || 8080;

app.use(express.json());

// Global timeout middleware (90 seconds by default)
app.use(timeoutMiddleware());

// API routes
app.use('/api', routes);

// Error handling middleware
app.use((err, req, res, next) => {
  console.error(err.stack);
  res.status(500).json({ error: 'Something went wrong!' });
});

app.listen(PORT, '0.0.0.0', () => {
  console.log(`Server is running on port ${PORT}`);
});
