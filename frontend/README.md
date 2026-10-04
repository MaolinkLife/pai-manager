# PAI frontend

The Angular 21 web interface of PAI. It is normally installed by `install.bat` and started together with the backend by `launch.bat`, both in the repository root.

Requires Node.js 20.19+, 22.12+ or 24+.

## Development server

`npm start` runs `ng serve` on port 3880 with `proxy.conf.json`, which forwards `/api` to the backend, the chat WebSocket included. When PAI is started with `launch.bat`, the ports come from `config/port-config.json` and the proxy target is synced from it.

## Build

`ng build` writes the production build to `dist/pai-manager/browser`.

## Unit tests

`ng test` runs the specs with Vitest in Node (jsdom), without a browser; `ng test --watch=false` runs them once.
