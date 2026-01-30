set -e

echo "Building frontend for Vercel..."

if [ -n "$VITE_API_URL" ]; then
    echo "Injecting API URL: $VITE_API_URL"

    sed -i "s|__VITE_API_URL__|$VITE_API_URL|g" config.js
else
    echo "WARNING: VITE_API_URL not set, using relative path /api"
    sed -i "s|__VITE_API_URL__|/api|g" config.js
fi

echo "Build complete!"
