import { Component, OnInit } from '@angular/core';
import { FormBuilder, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import { finalize } from 'rxjs/operators';
import { AuthService } from '../../core/services/auth.service';
import { AuthBootstrapState } from '../../core/models/auth.model';
import { NotificationService } from '../../shared/components/notification/notification.service';

type AuthMode = 'login' | 'register';

@Component({
    selector: 'app-auth',
    templateUrl: './auth.component.html',
    styleUrls: ['./auth.component.less'],
})
export class AuthComponent implements OnInit {
    mode: AuthMode = 'login';
    loading = false;
    bootstrapState: AuthBootstrapState | null = null;
    setupRequired = false;

    readonly loginForm = this.fb.group({
        identity: ['', [Validators.required]],
        password: ['', [Validators.required, Validators.minLength(8)]],
    });

    readonly registerForm = this.fb.group({
        email: ['', [Validators.required, Validators.email]],
        login: [''],
        name: [''],
        password: ['', [Validators.required, Validators.minLength(8)]],
        confirmPassword: ['', [Validators.required, Validators.minLength(8)]],
    });

    constructor(
        private fb: FormBuilder,
        private authService: AuthService,
        private notificationService: NotificationService,
        private router: Router
    ) { }

    ngOnInit(): void {
        this.authService.getBootstrapState$(true).subscribe({
            next: (state) => {
                this.bootstrapState = state;
                this.setupRequired = !state.has_owner;
                if (this.setupRequired) {
                    this.mode = 'register';
                }
            },
            error: () => {
                this.setupRequired = true;
                this.mode = 'register';
            },
        });
    }

    switchMode(mode: AuthMode): void {
        if (this.loading) {
            return;
        }
        if (this.setupRequired && mode === 'login') {
            return;
        }
        this.mode = mode;
    }

    submitLogin(): void {
        if (this.setupRequired) {
            this.notificationService.open({
                type: 'info',
                title: 'Первый запуск',
                message: 'Сначала создайте первый аккаунт (owner).',
                autoClose: true,
            });
            this.mode = 'register';
            return;
        }

        if (this.loading || this.loginForm.invalid) {
            this.loginForm.markAllAsTouched();
            return;
        }

        const identity = (this.loginForm.value.identity || '').trim();
        const password = this.loginForm.value.password || '';
        this.loading = true;

        this.authService
            .login$({ identity, password })
            .pipe(finalize(() => (this.loading = false)))
            .subscribe({
                next: () => this.router.navigateByUrl('/chat'),
                error: (error) => {
                    this.notificationService.open({
                        type: 'error',
                        title: 'Ошибка входа',
                        message: error?.error?.detail || 'Неверный логин/пароль.',
                        autoClose: true,
                    });
                },
            });
    }

    submitRegister(): void {
        if (this.loading || this.registerForm.invalid) {
            this.registerForm.markAllAsTouched();
            return;
        }

        const password = this.registerForm.value.password || '';
        const confirmPassword = this.registerForm.value.confirmPassword || '';
        if (password !== confirmPassword) {
            this.notificationService.open({
                type: 'warning',
                title: 'Проверьте пароль',
                message: 'Пароль и подтверждение не совпадают.',
                autoClose: true,
            });
            return;
        }

        const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
        const language = localStorage.getItem('language') || 'ru-RU';

        this.loading = true;
        this.authService
            .register$({
                email: (this.registerForm.value.email || '').trim(),
                login: (this.registerForm.value.login || '').trim() || undefined,
                name: (this.registerForm.value.name || '').trim() || undefined,
                password,
                language,
                timezone,
            })
            .pipe(finalize(() => (this.loading = false)))
            .subscribe({
                next: () => {
                    this.notificationService.open({
                        type: 'success',
                        title: 'Аккаунт создан',
                        autoClose: true,
                    });
                    this.router.navigateByUrl('/chat');
                },
                error: (error) => {
                    this.notificationService.open({
                        type: 'error',
                        title: 'Ошибка регистрации',
                        message: error?.error?.detail || 'Не удалось создать аккаунт.',
                        autoClose: true,
                    });
                },
            });
    }

    continueAsAnonymous(): void {
        if (this.loading) {
            return;
        }
        if (this.setupRequired || !this.bootstrapState?.allow_anonymous) {
            this.notificationService.open({
                type: 'info',
                title: 'Анонимный режим недоступен',
                message: 'Анонимный доступ станет доступен после создания owner аккаунта.',
                autoClose: true,
            });
            return;
        }
        this.authService.enterAnonymousMode();
        this.router.navigateByUrl('/chat');
    }
}
