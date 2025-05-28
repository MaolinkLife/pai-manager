import { Injectable } from '@angular/core';
import { Observable, of } from 'rxjs';
import { ProjectConfig } from '../models/project-config.model';
import { HttpClient } from '@angular/common/http';
import { ProjectConfigDto } from '../models/project-config.dto';
import { catchError, map } from 'rxjs/operators'
import { mapProjectConfigDtoToModel, mapPartialModelToDto } from '../utils/project-config.mapper';
import { environment } from '../../../environments/environment';


@Injectable({
    providedIn: 'root'
})
export class ConfigService {
    private apiUrl = environment.apiBaseUrl;

    constructor(private http: HttpClient) { }

    getConfig$(): Observable<ProjectConfig | null> {
        return this.http.get<ProjectConfigDto>(`${this.apiUrl}/config`).pipe(
            map(mapProjectConfigDtoToModel),
            catchError((_err) => {
                console.log({
                    _err
                });

                return of(null)
            })
        )
    }

    updateCongif$(body: ProjectConfig): Observable<any> {
        return this.http.patch(`${this.apiUrl}/config`, mapPartialModelToDto(body));
    }
}
