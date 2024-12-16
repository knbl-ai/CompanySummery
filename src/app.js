require('dotenv').config();
const express = require('express');
const routes = require('./routes/api');

const app = express();
const PORT = process.env.PORT || 8080;

app.use(express.json());

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
