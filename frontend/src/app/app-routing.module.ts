import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { LayoutComponent } from './layout/layout.component';
import { AuthGuard } from './core/guards/auth.guard';
import { GuestGuard } from './core/guards/guest.guard';
import { AuthenticatedUserGuard } from './core/guards/authenticated-user.guard';

const routes: Routes = [
    {
        path: 'auth',
        canActivate: [GuestGuard],
        loadChildren: () => import('./features/auth/auth.module').then(m => m.AuthModule),
    },
    {
        path: '',
        component: LayoutComponent,
        canActivate: [AuthGuard],
        canActivateChild: [AuthGuard],
        children: [
            { path: '', redirectTo: 'chat', pathMatch: 'full' },
            { path: 'chat', loadChildren: () => import('./features/chat/chat.module').then(m => m.ChatModule) },
            { path: 'memory', loadChildren: () => import('./features/memory/memory.module').then(m => m.MemoryModule) },
            { path: 'matrix', loadChildren: () => import('./features/matrix/matrix.module').then(m => m.MatrixModule) },
            { path: 'synthesis', loadChildren: () => import('./features/synthesis/synthesis.module').then(m => m.SynthesisModule) },
            { path: 'diary', loadChildren: () => import('./features/diary/diary.module').then(m => m.DiaryModule) },
            { path: 'audit', loadChildren: () => import('./features/audit/audit.module').then(m => m.AuditModule) },
            {
                path: 'settings',
                canActivate: [AuthenticatedUserGuard],
                loadChildren: () => import('./features/settings/settings.module').then(m => m.SettingsModule)
            },
            { path: 'tasks', loadChildren: () => import('./features/tasks/tasks.module').then(m => m.TasksModule) },
            { path: 'debug', loadChildren: () => import('./features/debug/debug.module').then(m => m.DebugModule) },
        ]
    },
    { path: '**', redirectTo: 'chat' },
];

@NgModule({
    imports: [RouterModule.forRoot(routes)],
    exports: [RouterModule]
})
export class AppRoutingModule { }
