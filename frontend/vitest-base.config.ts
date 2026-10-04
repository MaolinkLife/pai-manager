import { defineConfig } from 'vitest/config';

export default defineConfig({
    test: {
        server: {
            deps: {
                // RxJS 6 has no package exports: Angular's `rxjs/operators` is a
                // directory import that Node refuses. Bundling Angular through Vite
                // resolves it the way the application build does.
                inline: [/@angular\//],
            },
        },
    },
});
