import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { environment } from '../../../environments/environment';
import { ConfigService } from './config.service';

describe('ConfigService built-in defaults', () => {
    let service: ConfigService;
    let http: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [provideHttpClient(), provideHttpClientTesting()],
        });
        service = TestBed.inject(ConfigService);
        http = TestBed.inject(HttpTestingController);
    });

    afterEach(() => http.verify());

    it('reads a built-in value by its config path and asks the server once', () => {
        const values: unknown[] = [];

        service.getDefaultValue$('validator.system_prompt').subscribe((value) => values.push(value));
        service.getDefaultValue$('self_watcher.reflection_prompt').subscribe((value) => values.push(value));
        http.expectOne(`${environment.apiBaseUrl}/config/defaults`).flush({
            validator: { system_prompt: 'judge' },
            self_watcher: { reflection_prompt: 'reflect in {language}' },
        });

        expect(values).toEqual(['judge', 'reflect in {language}']);
    });

    it('gives nothing when the defaults cannot be loaded, and asks again next time', () => {
        const values: unknown[] = [];

        service.getDefaultValue$('validator.system_prompt').subscribe((value) => values.push(value));
        http.expectOne(`${environment.apiBaseUrl}/config/defaults`).flush('boom', { status: 500, statusText: 'Server Error' });
        service.getDefaultValue$('validator.system_prompt').subscribe((value) => values.push(value));
        http.expectOne(`${environment.apiBaseUrl}/config/defaults`).flush({ validator: { system_prompt: 'judge' } });

        expect(values).toEqual([null, 'judge']);
    });
});
