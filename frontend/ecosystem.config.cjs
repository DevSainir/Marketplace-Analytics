// PM2 process definition for the Vite dev server.
//
// Why this exists: unlike the backend (supervised by Docker with
// `restart: unless-stopped`), the frontend dev server had no supervisor and
// died whenever its parent shell/session went away. PM2 keeps it alive:
// it restarts vite on crash and — once `pm2 save` + `pm2 startup` are run —
// brings it back after a reboot.
//
// Usage (from anywhere):
//   pm2 start  frontend/ecosystem.config.cjs
//   pm2 logs   frontend
//   pm2 restart frontend
//   pm2 stop   frontend
//
// Note: `.cjs` extension is required because the frontend package.json sets
// "type": "module", which would otherwise make PM2 parse this as ESM.

const path = require('path');

module.exports = {
  apps: [
    {
      name: 'frontend',
      // Supervise vite directly (not `npm run dev`) so PM2 watches the real
      // process and its exit code, not an intermediary npm shell.
      cwd: __dirname,
      script: path.join(__dirname, 'node_modules/vite/bin/vite.js'),
      args: '--port 5173',
      interpreter: 'node',

      // Auto-recovery.
      autorestart: true,
      min_uptime: '5s', // must stay up 5s to count as a healthy start
      max_restarts: 100, // give up only after 100 rapid crash-loops
      restart_delay: 1000, // wait 1s between restarts to avoid tight loops

      // Do NOT use PM2's file watcher — vite has its own HMR. PM2 watching
      // the source tree would fight it and thrash on every save.
      watch: false,

      // Rotatable, timestamped logs under ~/.pm2/logs.
      time: true,

      env: {
        NODE_ENV: 'development',
      },
    },
  ],
};
