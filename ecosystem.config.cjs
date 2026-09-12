module.exports = {
  apps: [
    {
      name: 'trhaber',
      script: 'server.js',
      cwd: 'C:/mustafabuilds/TrHaberPlatformu',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '300M',
      env: {
        NODE_ENV: 'production',
        PORT: 3008
      },
      error_file: 'C:/nginx/logs/trhaber-error.log',
      out_file: 'C:/nginx/logs/trhaber-out.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z'
    }
  ]
};