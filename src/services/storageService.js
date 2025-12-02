const { Storage } = require('@google-cloud/storage');
const { v4: uuidv4 } = require('uuid');
const { withTimeout, getTimeoutFromEnv } = require('../utils/timeout');

class StorageService {
  constructor() {
    // Validate required environment variables
    if (!process.env.GCLOUD_STORAGE_BUCKET_NAME) {
      throw new Error('GCLOUD_STORAGE_BUCKET_NAME is required');
    }
    if (!process.env.GCLOUD_PROJECT_ID) {
      throw new Error('GCLOUD_PROJECT_ID is required');
    }
    if (!process.env.GCLOUD_CLIENT_EMAIL) {
      throw new Error('GCLOUD_CLIENT_EMAIL is required');
    }
    if (!process.env.GCLOUD_PRIVATE_KEY) {
      throw new Error('GCLOUD_PRIVATE_KEY is required');
    }

    // Initialize Storage client with credentials from env vars
    this.storage = new Storage({
      projectId: process.env.GCLOUD_PROJECT_ID,
      credentials: {
        client_email: process.env.GCLOUD_CLIENT_EMAIL,
        private_key: process.env.GCLOUD_PRIVATE_KEY
      }
    });

    this.bucketName = process.env.GCLOUD_STORAGE_BUCKET_NAME;
    this.bucket = this.storage.bucket(this.bucketName);
    this.publicAccess = process.env.GCS_PUBLIC_ACCESS !== 'false'; // default true
    this.signedUrlExpiry = parseInt(process.env.GCS_SIGNED_URL_EXPIRY || '3600');
  }

  generateFileName(format) {
    const uuid = uuidv4();
    const timestamp = Date.now();
    return `screenshot-${uuid}-${timestamp}.${format}`;
  }

  getContentType(format) {
    const contentTypeMap = {
      'png': 'image/png',
      'jpeg': 'image/jpeg',
      'webp': 'image/webp'
    };
    return contentTypeMap[format] || 'image/png';
  }

  async uploadScreenshot(buffer, options = {}) {
    const format = options.format || 'png';
    const fileName = this.generateFileName(format);
    const file = this.bucket.file(fileName);

    // Get configurable timeout from environment
    const GCS_UPLOAD_TIMEOUT = getTimeoutFromEnv('SCREENSHOT_GCS_UPLOAD_TIMEOUT', 15000);

    console.log(`Uploading ${buffer.length} bytes to GCS (timeout: ${GCS_UPLOAD_TIMEOUT}ms)...`);

    // Upload buffer with metadata - wrapped with timeout
    await withTimeout(
      file.save(buffer, {
        metadata: {
          contentType: this.getContentType(format),
          cacheControl: 'public, max-age=31536000',
        },
        validation: 'md5'
      }),
      GCS_UPLOAD_TIMEOUT,
      'GCS file upload'
    );

    console.log('File uploaded successfully to GCS');

    // Make public if configured
    if (this.publicAccess) {
      console.log('Making file public...');

      await withTimeout(
        file.makePublic(),
        10000,
        'GCS make public'
      );

      console.log('File made public successfully');

      return {
        url: `https://storage.googleapis.com/${this.bucketName}/${fileName}`,
        fileName,
        fileSize: buffer.length,
        contentType: this.getContentType(format)
      };
    } else {
      // Generate signed URL
      console.log('Generating signed URL...');

      const [signedUrl] = await withTimeout(
        file.getSignedUrl({
          action: 'read',
          expires: Date.now() + (this.signedUrlExpiry * 1000)
        }),
        10000,
        'GCS signed URL generation'
      );

      console.log('Signed URL generated successfully');

      return {
        url: signedUrl,
        fileName,
        fileSize: buffer.length,
        contentType: this.getContentType(format)
      };
    }
  }
}

module.exports = new StorageService();
