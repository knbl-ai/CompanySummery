require('dotenv').config();
const express = require('express');
const helmet = require('helmet');
const routes = require('./routes/api');
const timeoutMiddleware = require('./middleware/timeout');
const rateLimiter = require('./middleware/rateLimiter');
const { corsMiddleware } = require('./middleware/cors');

const app = express();
const PORT = process.env.PORT || 8080;

// Trust Cloud Run proxy
app.set('trust proxy', true);

// Security headers (helmet)
app.use(helmet());

// Rate limiting - apply before other middleware
app.use(rateLimiter);

// CORS middleware
app.use(corsMiddleware);

// Body parsing
app.use(express.json());

// Global timeout middleware (90 seconds by default)
app.use(timeoutMiddleware());

// API routes
app.use('/api', routes);

// Error handling middleware
app.use((err, req, res, next) => {
  // Log detailed error server-side
  console.error('Server error:', err.message);

  // Handle CORS errors
  if (err.message === 'Not allowed by CORS') {
    return res.status(403).json({
      error: 'Access denied',
      message: 'Cross-origin request not allowed'
    });
  }

  // Return generic error to client
  res.status(500).json({ error: 'Internal server error' });
});

app.listen(PORT, '0.0.0.0', () => {
  console.log(`Server is running on port ${PORT}`);
});
