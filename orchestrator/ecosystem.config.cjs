module.exports = {
  apps: [
    {
      name: "clade-orchestrator",
      script: ".venv/bin/uvicorn",
      args: "server:app --host 127.0.0.1 --port 8010",
      cwd: "/home/alexshen/projects/clade/orchestrator",
      interpreter: "none",
      autorestart: true,
      watch: false,
      max_memory_restart: "512M",
      env: {
        PYTHONUNBUFFERED: "1",
        ORCHESTRATOR_PROJECT_DIR: "/home/alexshen/projects/clade",
      },
      log_date_format: "YYYY-MM-DD HH:mm:ss",
    },
  ],
};
