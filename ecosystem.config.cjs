module.exports = {
  apps: [
    {
      name: "crm-backend",
      cwd: "/home/ubuntu/Python_Visualization",
      script: "/home/ubuntu/Python_Visualization/venv/bin/uvicorn",
      args: "backend.main:app --host 127.0.0.1 --port 8000 --workers 2",
      interpreter: "none",
      autorestart: true,
      watch: false,
      max_restarts: 50,
      restart_delay: 3000,
      env: {
        PYTHONUNBUFFERED: "1"
      }
    }
  ]
};
