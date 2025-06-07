import { Component, OnInit } from '@angular/core';
import { LoggerService } from '../../core/services/logger.service';

import {
    trigger,
    state,
    style,
    transition,
    animate
} from '@angular/animations';

@Component({
    selector: 'app-debug',
    templateUrl: './debug.component.html',
    styleUrls: ['./debug.component.less'],
    animations: [
        trigger('expandCollapse', [
            state('closed', style({ height: '0px', opacity: 0, overflow: 'hidden' })),
            state('open', style({ height: '*', opacity: 1 })),
            transition('closed <=> open', [animate('200ms ease-in-out')])
        ])
    ]
})
export class DebugComponent implements OnInit {


    logs: any = [];

    expandedLogs: Set<number> = new Set();

    constructor(private loggerService: LoggerService) { }

    ngOnInit(): void {
        this.loggerService.getDebugLog$().subscribe((logs) => {
            console.log({
                logs
            });

            this.logs = logs.sort((a, b) => {
                return new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime();
            });
        });
    }

    toggleDetails(index: number): void {
        if (this.expandedLogs.has(index)) {
            this.expandedLogs.delete(index);
        } else {
            this.expandedLogs.add(index);
        }
    }

    getLogClass(log: any): string {

        if (log.status === 'Error' || log.meta?.severity === 'error' || log.event_type === 'error') {
            return 'error';
        }

        if (log.status === "Success" || log.details?.status === 'OK' || log.details?.status === 'success') {
            return 'success';
        }

        // if (log.event_type?.toLowerCase().includes('startup')) {
        //     return 'success';
        // }

        // if (log.event_type?.toLowerCase().includes('debug')) {
        //     return 'debug';
        // }

        return 'audit'; // базовый стиль
    }
}
