const cors = require('cors');

// Allowed origins - only these domains can access the API from browsers
const ALLOWED_ORIGINS = [
  'https://igentity.ai',
  'https://www.igentity.ai',
  'https://socialmediaserveragent.xyz',
  'https://www.socialmediaserveragent.xyz'
];

// CORS configuration
const corsOptions = {
  origin: function (origin, callback) {
    // Allow requests with no origin (server-to-server)
    // or requests from allowed origins (browser)
    if (!origin || ALLOWED_ORIGINS.includes(origin)) {
      callback(null, true);
    } else {
      callback(new Error('Not allowed by CORS'));
    }
  },
  methods: ['GET', 'POST', 'OPTIONS'],
  allowedHeaders: ['Content-Type', 'Authorization'],
  credentials: true,
  maxAge: 86400 // 24 hours
};

// CORS middleware
const corsMiddleware = cors(corsOptions);

module.exports = {
  corsMiddleware,
  ALLOWED_ORIGINS
};
