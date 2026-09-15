import { Observable, Subject, of, throwError } from 'rxjs';
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

describe('WebsocketService', () => {
    const realWebSocket = window.WebSocket;
    let passes: number;

    beforeEach(() => {
        FakeSocket.instances = [];
        passes = 0;
        (window as any).WebSocket = FakeSocket;
        jasmine.clock().install();
    });

    afterEach(() => {
        jasmine.clock().uninstall();
        (window as any).WebSocket = realWebSocket;
    });

    function signedIn(requestWsTicket$: () => Observable<string> = () => of(`pass-${++passes}`)): any {
        return {
            getAccessToken: () => 'secret-access-token',
            isAuthenticated: () => true,
            isAnonymousMode: () => false,
            requestWsTicket$: jasmine.createSpy('requestWsTicket$').and.callFake(requestWsTicket$),
        };
    }

    it('says so when a dropped connection comes back, not on the first connect', () => {
        const service = new WebsocketService(signedIn());
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

    it('opens the socket with a one-time pass and never puts the access token into the address', () => {
        const service = new WebsocketService(signedIn());

        service.connect();

        expect(FakeSocket.instances[0].url).toMatch(/\/api\/ws\?ticket=pass-1$/);
        expect(FakeSocket.instances[0].url).not.toContain('secret-access-token');
        expect(FakeSocket.instances[0].url).not.toContain('access_token');
    });

    it('asks for a fresh pass for every new connection', () => {
        const service = new WebsocketService(signedIn());

        service.connect();
        FakeSocket.instances[0].open();
        FakeSocket.instances[0].drop();
        jasmine.clock().tick(1000);

        expect(FakeSocket.instances[1].url).toMatch(/\?ticket=pass-2$/);
    });

    it('lets an anonymous guest connect without a pass', () => {
        const auth: any = {
            getAccessToken: () => null,
            isAuthenticated: () => false,
            isAnonymousMode: () => true,
            requestWsTicket$: jasmine.createSpy('requestWsTicket$'),
        };
        const service = new WebsocketService(auth);

        service.connect();

        expect(FakeSocket.instances[0].url).toMatch(/\/api\/ws$/);
        expect(auth.requestWsTicket$).not.toHaveBeenCalled();
    });

    it('tries again later when the pass could not be had', () => {
        let attempts = 0;
        const service = new WebsocketService(signedIn(() => (++attempts === 1 ? throwError(() => new Error('offline')) : of('pass-late'))));

        service.connect();
        expect(FakeSocket.instances.length).toBe(0);

        jasmine.clock().tick(1000);

        expect(FakeSocket.instances.length).toBe(1);
        expect(FakeSocket.instances[0].url).toMatch(/\?ticket=pass-late$/);
    });

    it('opens no socket when it was disconnected while the pass was on its way', () => {
        const pass$ = new Subject<string>();
        const service = new WebsocketService(signedIn(() => pass$));

        service.connect();
        service.disconnect();
        pass$.next('pass-too-late');

        expect(FakeSocket.instances.length).toBe(0);
    });
});
