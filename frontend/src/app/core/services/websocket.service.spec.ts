import { WebsocketService } from './websocket.service';

class FakeSocket {
    static readonly OPEN = 1;
    static instances: FakeSocket[] = [];

    readyState = 0;
    onopen: (() => void) | null = null;
    onclose: (() => void) | null = null;
    onmessage: ((event: { data: string }) => void) | null = null;
    onerror: ((error: unknown) => void) | null = null;

    constructor(public url: string) {
        FakeSocket.instances.push(this);
    }

    send(): void {}

    close(): void {
        this.drop();
    }

    open(): void {
        this.readyState = FakeSocket.OPEN;
        this.onopen?.();
    }

    drop(): void {
        this.readyState = 3;
        this.onclose?.();
    }
}

describe('WebsocketService: reconnecting', () => {
    const realWebSocket = window.WebSocket;

    beforeEach(() => {
        FakeSocket.instances = [];
        (window as any).WebSocket = FakeSocket;
        jasmine.clock().install();
    });

    afterEach(() => {
        jasmine.clock().uninstall();
        (window as any).WebSocket = realWebSocket;
    });

    function create(): WebsocketService {
        const auth: any = { getAccessToken: () => null, isAuthenticated: () => true, isAnonymousMode: () => false };
        return new WebsocketService(auth);
    }

    it('says so when a dropped connection comes back, not on the first connect', () => {
        const service = create();
        let reconnects = 0;
        service.reconnected$.subscribe(() => reconnects++);

        service.connect();
        FakeSocket.instances[0].open();
        expect(reconnects).toBe(0);

        FakeSocket.instances[0].drop();
        jasmine.clock().tick(1000);
        FakeSocket.instances[1].open();

        expect(reconnects).toBe(1);
    });
});
