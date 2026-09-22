#!/bin/sh
# Start the API and the UI in one container, and die if either of them dies.
#
# Two processes rather than two services because they are not independently
# useful: the UI is the only client of this API, and the API binds container
# loopback so nothing outside can reach it anyway. Splitting them would publish
# a port that authenticates nobody.
#
#   API       127.0.0.1:${VITESS_API_PORT}   container loopback, never published
#   UI        0.0.0.0:${UI_PORT}             published on the host's loopback
#
# `set -e` is not enough on its own: a shell that has backgrounded two children
# exits 0 when the script ends. So the loop at the bottom waits until the
# *first* of them stops and takes the container down with it -- a UI still
# serving pages against a dead API is the failure this avoids, because it looks
# like it works.
#
# The loop polls rather than using `wait -n`, which is a bash builtin: this
# image's /bin/sh is dash, where `wait -n` is an "Illegal option" and the script
# falls straight through to its own exit. That failed by restarting the
# container every few seconds, which at least was loud.
set -eu

API_PORT="${VITESS_API_PORT:-9600}"
UI_PORT="${UI_PORT:-9601}"
BIND_HOST="${VITESS_BIND_HOST:-127.0.0.1}"

echo "vitess-ai: API on ${BIND_HOST}:${API_PORT}, UI on 0.0.0.0:${UI_PORT}"

uvicorn vitess_ai.server.service:app --host "${BIND_HOST}" --port "${API_PORT}" &
api_pid=$!

streamlit run app/streamlit_app.py \
    --server.address 0.0.0.0 \
    --server.port "${UI_PORT}" \
    --server.headless true \
    --browser.gatherUsageStats false &
ui_pid=$!

# Report which one went, so the compose log says why the container stopped.
while kill -0 "${api_pid}" 2>/dev/null && kill -0 "${ui_pid}" 2>/dev/null; do
    sleep 2
done

if kill -0 "${api_pid}" 2>/dev/null; then
    gone="the UI"
else
    gone="the API"
fi
kill "${api_pid}" "${ui_pid}" 2>/dev/null || true
wait "${api_pid}" 2>/dev/null || status=$?
wait "${ui_pid}" 2>/dev/null || status=${status:-$?}
echo "vitess-ai: ${gone} exited; stopping the container"
exit "${status:-1}"
