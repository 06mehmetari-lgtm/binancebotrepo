#!/bin/bash
set -e
cd ~/prometheus
LOG=/tmp/prom_build.log
echo "build start $(date -Iseconds)" > "$LOG"
docker compose build dashboard oms agent_system learning_engine signal_engine >> "$LOG" 2>&1
echo "BUILD_EXIT:$?" >> "$LOG"
docker compose up -d --force-recreate dashboard oms agent_system learning_engine signal_engine >> "$LOG" 2>&1
echo "deploy done $(date -Iseconds)" >> "$LOG"
