import { Component, OnInit } from '@angular/core';
import { LoggerService } from '../../core/services/logger.service';

@Component({
    selector: 'app-debug',
    templateUrl: './debug.component.html',
    styleUrls: ['./debug.component.less']
})
export class DebugComponent implements OnInit {

    logs: any = [];

    constructor(private loggerService: LoggerService) { }

    ngOnInit(): void {
        this.loggerService.getDebugLog$().subscribe((logs) => {
            console.log({
                logs
            });
            this.logs = logs
        })
    }

    getLogClass(log: any): string {
        if (log.meta?.severity === 'error' || log.event_type === 'error') {
            return 'error';
        }

        if (log.details?.status === 'OK' || log.details?.status === 'success') {
            return 'success';
        }

        if (log.event_type?.toLowerCase().includes('startup')) {
            return 'success';
        }

        if (log.event_type?.toLowerCase().includes('debug')) {
            return 'debug';
        }

        return 'audit'; // базовый стиль
    }
}
