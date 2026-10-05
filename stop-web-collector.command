#!/bin/zsh
set -eu
launchctl bootout "gui/$(id -u)/app.review-port.collector" 2>/dev/null || true
print 'Review Portの収集サービスを停止しました。'
