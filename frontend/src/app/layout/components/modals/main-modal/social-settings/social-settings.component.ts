import { ChangeDetectorRef, Component, NgZone, OnInit } from '@angular/core';
import { UntypedFormBuilder, UntypedFormGroup } from '@angular/forms';
import { ConfigService } from '../../../../../core/services/config.service';
import { TelegramBridgeStatus, TelegramChatPeer, TelegramService } from '../../../../../core/services/telegram.service';
import { LocalizationService } from '../../../../../shared/pipes/translation/localization.service';
import { UiNotificationService } from '../../../../../shared/ui/services/ui-notification.service';
import { UiSelectOption } from '../../../../../shared/ui/components/ui-select/ui-select.component';

@Component({
    selector: 'app-social-settings',
    templateUrl: './social-settings.component.html',
    styleUrls: ['./social-settings.component.less']
})
export class SocialSettingsComponent implements OnInit {
    socialForm: UntypedFormGroup;
    originalConfig: any = {};
    telegramBaseConfig: any = {};
    telegramStatus: TelegramBridgeStatus | null = null;
    isTelegramBusy = false;
    authPhoneInput = '';
    authCodeInput = '';
    authPasswordInput = '';
    allowedChatIdsInput = '';
    allowedPrivateChatIdsInput = '';
    sandboxChatIdsInput = '';
    reflectionSourceChatIdsInput = '';
    telegramPeers: TelegramChatPeer[] = [];
    ownerChatOptions: UiSelectOption[] = [];
    reflectionTargetOptions: UiSelectOption[] = [];
    isPeersLoading = false;
    private readonly legacyReflectionPrompt =
        'Read the public Telegram post below and write a short private reflection for the owner. Do not address the public chat. Do not write as a reply to the channel. Summarize what happened, what LIM thinks about it, and why it may matter.';
    private readonly legacyChannelReflectionInstruction =
        'Reflect shortly on key facts and implications from this channel post.';
    private readonly legacyInitiativePrompt =
        'You have not heard from this chat for {idle_minutes} minutes. Send one short warm proactive message, if appropriate.';
    private readonly legacyAutonomousInboxPrompt =
        'You are online and received unread events in Telegram. Choose one action: open chat, answer, read channel, or pause.';

    constructor(
        private fb: UntypedFormBuilder,
        private configService: ConfigService,
        private telegramService: TelegramService,
        private localizationService: LocalizationService,
        private uiNotificationService: UiNotificationService,
        private cdr: ChangeDetectorRef,
        private ngZone: NgZone,
    ) {
        this.socialForm = this.createForm();
    }

    ngOnInit(): void {
        this.localizationService.init();
        this.loadConfig();
        this.initCommunicationFormRules();
        this.refreshTelegramStatus();
    }

    get telegramModeOptions(): UiSelectOption[] {
        return [
            { value: 'mtproto', label: this.t('socialSettings.telegram.modeMtproto') },
            { value: 'bot', label: this.t('socialSettings.telegram.modeBot') },
        ];
    }

    get communicationPrimaryOptions(): UiSelectOption[] {
        return [
            { value: 'main_chat', label: this.t('socialSettings.communication.mainChatCore') },
            { value: 'telegram', label: this.t('socialSettings.communication.telegram') },
        ];
    }

    t(key: string): string {
        return this.localizationService.t(key);
    }

    private createForm(): UntypedFormGroup {
        return this.fb.group({
            modules: this.fb.group({
                discord: [false],
                telegram: [false],
            }),
            telegram: this.fb.group({
                enabled: [false],
                mode: ['mtproto'],
                api_id: [0],
                api_hash: [''],
                session_name: ['z_waif'],
                session_dir: ['data/telegram'],
                phone_number: [''],
                bot_token: [''],
                queue_size: [256],
                history_max_messages: [24],
                routing: this.fb.group({
                    allow_private: [true],
                    allow_groups: [true],
                    allow_channels: [true],
                    write_private: [true],
                    write_groups: [true],
                    write_channels: [false],
                    read_only_non_private: [true],
                    groups_require_mention: [false],
                    allowed_chat_ids: this.fb.control([]),
                }),
                write_policy: this.fb.group({
                    allow_private: [true],
                    allow_groups: [false],
                    allow_channels: [false],
                    allowed_private_chat_ids: this.fb.control([]),
                    denied_chat_ids: this.fb.control([]),
                    sandbox_chat_ids: this.fb.control([]),
                }),
                anti_spam: this.fb.group({
                    per_chat_max_messages: [5],
                    global_max_messages: [24],
                    window_seconds: [15.0],
                    min_delay_seconds: [0.7],
                }),
                anti_repeat: this.fb.group({
                    enforce_for_incoming_dialogs: [false],
                    retry_on_block: [true],
                    retry_attempts: [1],
                }),
                channels: this.fb.group({
                    read_enabled: [true],
                    mark_read_enabled: [true],
                    reflect_enabled: [false],
                    reflection_instruction: [''],
                }),
                reflection: this.fb.group({
                    enabled: [true],
                    source_chat_ids: this.fb.control([]),
                    source_chat_kinds: this.fb.control(['channel', 'group']),
                    target_chat_id: [0],
                    prompt: [''],
                    include_source_excerpt: [true],
                    include_source_link: [true],
                    max_source_excerpt_chars: [800],
                    max_reflection_length: [1200],
                    min_source_text_chars: [25],
                    cooldown_per_source_chat_seconds: [90],
                }),
                quiet_hours: this.fb.group({
                    enabled: [true],
                    start: ['00:00'],
                    end: ['09:00'],
                }),
                lockdown: this.fb.group({
                    enabled: [false],
                    owner_chat_id: [0],
                }),
                initiative: this.fb.group({
                    enabled: [false],
                    check_every_seconds: [60],
                    idle_minutes: [60],
                    min_gap_minutes: [30],
                    max_proactive_per_day: [3],
                    morning_checkin_enabled: [true],
                    evening_checkin_enabled: [true],
                    daily_digest_enabled: [true],
                    daily_digest_window_start: ['20:00'],
                    daily_digest_window_end: ['22:00'],
                    owner_chat_only: [true],
                    bootstrap_from_catalog: [true],
                    bootstrap_max_chats: [64],
                    allow_private: [true],
                    allow_groups: [false],
                    prompt_template: [''],
                }),
                autonomous_inbox: this.fb.group({
                    enabled: [false],
                    check_every_seconds: [45],
                    max_candidates: [8],
                    max_actions_per_cycle: [2],
                    include_private: [true],
                    include_groups: [true],
                    include_channels: [true],
                    private_pause_probability: [0.2],
                    prompt_template: [''],
                }),
                presence: this.fb.group({
                    enabled: [true],
                    auto_offline_after_send: [true],
                }),
                orchestration: this.fb.group({
                    allow_llm_tool_actions: [false],
                    require_tool_call: [false],
                    max_no_tool_retries: [2],
                    tools: this.fb.group({
                        ask_google: [true],
                    }),
                }),
                image: this.fb.group({
                    autonomous_random_enabled: [false],
                    autonomous_random_probability: [0.5],
                }),
            }),
            communication: this.fb.group({
                primary_channel: ['main_chat'],
                channels: this.fb.group({
                    main_chat: this.fb.group({
                        enabled: [true],
                        allow_fallback: [false],
                    }),
                    telegram: this.fb.group({
                        enabled: [true],
                        allow_fallback: [true],
                    }),
                }),
            }),
        });
    }

    private loadConfig(): void {
        this.configService.getConfig$().subscribe((config: any) => {
            this.uiUpdate(() => {
                const next = {
                    modules: {
                        discord: !!config?.modules?.discord,
                        telegram: !!config?.modules?.telegram,
                    },
                    telegram: config?.telegram || {},
                    communication: this.mapCommunicationToForm(config?.communication),
                };
                this.socialForm.patchValue(next);
                this.telegramBaseConfig = this.deepClone(config?.telegram || {});
                this.originalConfig = this.buildConfigFromForm();
                this.applyLocalizedDefaults();
                this.syncAllowedChatIdsTextFromForm();
                this.syncWritePolicyTextFromForm();
                this.syncReflectionSourceChatIdsTextFromForm();
                this.rebuildOwnerChatOptions();
            });
        });
    }

    saveChanges(): void {
        this.enforceCommunicationRules(false);
        this.syncAllowedChatIdsFormFromText();
        this.syncWritePolicyFormFromText();
        this.syncReflectionSourceChatIdsFormFromText();
        const current = this.buildConfigFromForm();
        const updateData: any = {};
        if (JSON.stringify(current.modules) !== JSON.stringify(this.originalConfig.modules)) {
            updateData.modules = current.modules;
        }
        if (JSON.stringify(current.telegram) !== JSON.stringify(this.originalConfig.telegram)) {
            updateData.telegram = current.telegram;
        }
        if (JSON.stringify(current.communication) !== JSON.stringify(this.originalConfig.communication)) {
            updateData.communication = current.communication;
        }
        if (Object.keys(updateData).length === 0) {
            return;
        }
        this.configService.updateConfig$(updateData).subscribe({
            next: () => {
                this.originalConfig = current;
                this.telegramBaseConfig = this.deepClone(current.telegram || {});
                this.uiNotificationService.success(
                    this.t('socialSettings.notifications.updated'),
                    this.t('socialSettings.title')
                );
            },
            error: (error) => {
                console.error('Social settings update error:', error);
                this.uiNotificationService.error(
                    this.t('socialSettings.notifications.updateFailed'),
                    this.t('socialSettings.title')
                );
            },
        });
    }

    hasChanges(): boolean {
        const current = this.buildConfigFromForm();
        return JSON.stringify(current) !== JSON.stringify(this.originalConfig);
    }

    private buildConfigFromForm(): any {
        const value = this.socialForm.value;
        return {
            modules: value.modules,
            telegram: this.deepMerge(this.deepClone(this.telegramBaseConfig || {}), value.telegram || {}),
            communication: this.mapCommunicationFromForm(value.communication),
        };
    }

    refreshTelegramStatus(silent = false, refreshPeers = true): void {
        if (!silent) {
            this.isTelegramBusy = true;
        }
        this.telegramService.getStatus$().subscribe({
            next: (response) => {
                this.uiUpdate(() => {
                    this.telegramStatus = response?.telegram || null;
                    if (refreshPeers) {
                        if (this.telegramStatus?.running && this.telegramStatus?.auth_state !== 'starting') {
                            this.loadTelegramPeers();
                        } else {
                            this.telegramPeers = [];
                            this.rebuildOwnerChatOptions();
                        }
                    }
                    if (!silent) {
                        this.isTelegramBusy = false;
                    }
                });
            },
            error: (error) => {
                console.error('Telegram status error:', error);
                this.uiUpdate(() => {
                    if (refreshPeers) {
                        this.telegramPeers = [];
                        this.rebuildOwnerChatOptions();
                    }
                    if (!silent) {
                        this.isTelegramBusy = false;
                    }
                });
            },
        });
    }

    startTelegram(): void {
        this.isTelegramBusy = true;
        this.telegramService.start$().subscribe({
            next: (response) => {
                this.uiUpdate(() => {
                    this.telegramStatus = response?.telegram || null;
                    this.isTelegramBusy = false;
                    this.uiNotificationService.success(
                        this.t('socialSettings.notifications.bridgeStartRequested'),
                        this.t('socialSettings.telegram.bridge')
                    );
                    this.telegramPeers = [];
                    this.rebuildOwnerChatOptions();
                });
            },
            error: (error) => {
                console.error('Telegram start error:', error);
                this.uiUpdate(() => {
                    this.isTelegramBusy = false;
                    this.uiNotificationService.error(
                        this.t('socialSettings.notifications.bridgeStartFailed'),
                        this.t('socialSettings.telegram.bridge')
                    );
                });
            },
        });
    }

    stopTelegram(): void {
        this.isTelegramBusy = true;
        this.telegramService.stop$().subscribe({
            next: (response) => {
                this.uiUpdate(() => {
                    this.telegramStatus = response?.telegram || null;
                    this.isTelegramBusy = false;
                    this.uiNotificationService.success(
                        this.t('socialSettings.notifications.bridgeStopped'),
                        this.t('socialSettings.telegram.bridge')
                    );
                    this.telegramPeers = [];
                    this.rebuildOwnerChatOptions();
                });
            },
            error: (error) => {
                console.error('Telegram stop error:', error);
                this.uiUpdate(() => {
                    this.isTelegramBusy = false;
                    this.uiNotificationService.error(
                        this.t('socialSettings.notifications.bridgeStopFailed'),
                        this.t('socialSettings.telegram.bridge')
                    );
                });
            },
        });
    }

    pingTelegram(): void {
        this.isTelegramBusy = true;
        this.telegramService.ping$().subscribe({
            next: (response) => {
                this.uiUpdate(() => {
                    this.isTelegramBusy = false;
                    if (response?.ping?.ok) {
                        const latency = response?.ping?.latency_ms;
                        this.uiNotificationService.success(
                            typeof latency === 'number' ? `${latency} ms` : this.t('socialSettings.status.ok'),
                            this.t('socialSettings.telegram.pingTitle')
                        );
                    } else {
                        this.uiNotificationService.error(
                            response?.ping?.error || this.t('socialSettings.notifications.pingFailed'),
                            this.t('socialSettings.telegram.pingTitle')
                        );
                    }
                    this.refreshTelegramStatus(true);
                });
            },
            error: (error) => {
                console.error('Telegram ping error:', error);
                this.uiUpdate(() => {
                    this.isTelegramBusy = false;
                    this.uiNotificationService.error(
                        this.t('socialSettings.notifications.pingRequestFailed'),
                        this.t('socialSettings.telegram.pingTitle')
                    );
                });
            },
        });
    }

    loadTelegramPeers(): void {
        if (this.isPeersLoading) {
            return;
        }
        this.isPeersLoading = true;
        this.telegramService.listChats$().subscribe({
            next: (response) => {
                this.uiUpdate(() => {
                    this.telegramPeers = Array.isArray(response?.chats) ? response.chats : [];
                    this.rebuildOwnerChatOptions();
                    this.isPeersLoading = false;
                });
            },
            error: (error) => {
                console.error('Telegram peers error:', error);
                this.uiUpdate(() => {
                    this.telegramPeers = [];
                    this.rebuildOwnerChatOptions();
                    this.isPeersLoading = false;
                });
            },
        });
    }

    runPublicReflectionTest(): void {
        const sourceChatId = this.resolveReflectionProbeSourceChatId();
        this.isTelegramBusy = true;
        this.telegramService.testPublicReflection$(sourceChatId).subscribe({
            next: (response) => {
                this.uiUpdate(() => {
                    this.isTelegramBusy = false;
                    const probe = response?.probe || {};
                    if (probe?.ok) {
                        this.uiNotificationService.success(
                            `${this.t('socialSettings.tests.publicReflectionSuccess')} chat_id=${probe.source_chat_id}`,
                            this.t('socialSettings.telegram.bridge')
                        );
                    } else {
                        this.uiNotificationService.error(
                            probe?.error || this.t('socialSettings.tests.publicReflectionFailed'),
                            this.t('socialSettings.telegram.bridge')
                        );
                    }
                });
            },
            error: (error) => {
                console.error('Telegram public reflection test error:', error);
                this.uiUpdate(() => {
                    this.isTelegramBusy = false;
                    this.uiNotificationService.error(
                        this.t('socialSettings.tests.publicReflectionFailed'),
                        this.t('socialSettings.telegram.bridge')
                    );
                });
            },
        });
    }

    runImageSendTest(): void {
        const targetChatId = this.resolveImageTestTargetChatId();
        this.isTelegramBusy = true;
        this.telegramService.testSendImage$(targetChatId).subscribe({
            next: (response) => {
                this.uiUpdate(() => {
                    this.isTelegramBusy = false;
                    const imageTest = response?.image_test || {};
                    if (imageTest?.ok) {
                        this.uiNotificationService.success(
                            `${this.t('socialSettings.tests.imageSendSuccess')} chat_id=${imageTest.target_chat_id}`,
                            this.t('socialSettings.telegram.bridge')
                        );
                    } else {
                        this.uiNotificationService.error(
                            imageTest?.error || this.t('socialSettings.tests.imageSendFailed'),
                            this.t('socialSettings.telegram.bridge')
                        );
                    }
                });
            },
            error: (error) => {
                console.error('Telegram image send test error:', error);
                this.uiUpdate(() => {
                    this.isTelegramBusy = false;
                    this.uiNotificationService.error(
                        this.t('socialSettings.tests.imageSendFailed'),
                        this.t('socialSettings.telegram.bridge')
                    );
                });
            },
        });
    }

    private uiUpdate(work: () => void): void {
        this.ngZone.run(() => {
            work();
            this.cdr.detectChanges();
        });
    }

    requestTelegramCode(): void {
        this.isTelegramBusy = true;
        const phone = String(this.authPhoneInput || '').trim() || undefined;
        this.telegramService.requestCode$(phone).subscribe({
            next: (response) => {
                this.isTelegramBusy = false;
                const auth = response?.auth;
                if (auth?.ok) {
                    this.uiNotificationService.success(
                        auth.state || this.t('socialSettings.notifications.codeRequested'),
                        this.t('socialSettings.telegram.authTitle')
                    );
                } else {
                    this.uiNotificationService.error(
                        auth?.error || this.t('socialSettings.notifications.codeRequestFailed'),
                        this.t('socialSettings.telegram.authTitle')
                    );
                }
                this.refreshTelegramStatus();
            },
            error: (error) => {
                console.error('Telegram request code error:', error);
                this.isTelegramBusy = false;
                this.uiNotificationService.error(
                    this.t('socialSettings.notifications.codeRequestFailed'),
                    this.t('socialSettings.telegram.authTitle')
                );
            },
        });
    }

    submitTelegramCode(): void {
        const code = String(this.authCodeInput || '').trim();
        if (!code) {
            this.uiNotificationService.error(
                this.t('socialSettings.notifications.codeRequired'),
                this.t('socialSettings.telegram.authTitle')
            );
            return;
        }
        this.isTelegramBusy = true;
        this.telegramService.submitCode$(code).subscribe({
            next: (response) => {
                this.isTelegramBusy = false;
                const auth = response?.auth;
                if (auth?.ok) {
                    this.uiNotificationService.success(
                        auth.state || this.t('socialSettings.notifications.authorized'),
                        this.t('socialSettings.telegram.authTitle')
                    );
                } else {
                    this.uiNotificationService.error(
                        auth?.error || this.t('socialSettings.notifications.invalidCode'),
                        this.t('socialSettings.telegram.authTitle')
                    );
                }
                this.refreshTelegramStatus();
            },
            error: (error) => {
                console.error('Telegram submit code error:', error);
                this.isTelegramBusy = false;
                this.uiNotificationService.error(
                    this.t('socialSettings.notifications.codeSubmitFailed'),
                    this.t('socialSettings.telegram.authTitle')
                );
            },
        });
    }

    submitTelegramPassword(): void {
        const password = String(this.authPasswordInput || '');
        if (!password.trim()) {
            this.uiNotificationService.error(
                this.t('socialSettings.notifications.passwordRequired'),
                this.t('socialSettings.telegram.authTitle')
            );
            return;
        }
        this.isTelegramBusy = true;
        this.telegramService.submitPassword$(password).subscribe({
            next: (response) => {
                this.isTelegramBusy = false;
                const auth = response?.auth;
                if (auth?.ok) {
                    this.uiNotificationService.success(
                        auth.state || this.t('socialSettings.notifications.authorized'),
                        this.t('socialSettings.telegram.authTitle')
                    );
                } else {
                    this.uiNotificationService.error(
                        auth?.error || this.t('socialSettings.notifications.passwordRejected'),
                        this.t('socialSettings.telegram.authTitle')
                    );
                }
                this.refreshTelegramStatus();
            },
            error: (error) => {
                console.error('Telegram submit password error:', error);
                this.isTelegramBusy = false;
                this.uiNotificationService.error(
                    this.t('socialSettings.notifications.passwordSubmitFailed'),
                    this.t('socialSettings.telegram.authTitle')
                );
            },
        });
    }

    private initCommunicationFormRules(): void {
        const primaryControl = this.socialForm.get('communication.primary_channel');
        const mainEnabledControl = this.socialForm.get('communication.channels.main_chat.enabled');
        const telegramEnabledControl = this.socialForm.get('communication.channels.telegram.enabled');

        primaryControl?.valueChanges.subscribe(() => this.enforceCommunicationRules(true));
        mainEnabledControl?.valueChanges.subscribe(() => this.enforceCommunicationRules(true));
        telegramEnabledControl?.valueChanges.subscribe(() => this.enforceCommunicationRules(true));
    }

    private enforceCommunicationRules(notify: boolean): void {
        const primary = String(this.socialForm.get('communication.primary_channel')?.value || 'main_chat');
        const mainPath = 'communication.channels.main_chat.enabled';
        const telegramPath = 'communication.channels.telegram.enabled';
        const telegramFallbackPath = 'communication.channels.telegram.allow_fallback';

        const mainEnabled = !!this.socialForm.get(mainPath)?.value;
        const telegramEnabled = !!this.socialForm.get(telegramPath)?.value;

        if (!mainEnabled && !telegramEnabled) {
            const fallbackChannel = primary === 'telegram' ? telegramPath : mainPath;
            this.socialForm.get(fallbackChannel)?.setValue(true, { emitEvent: false });
            if (notify) {
                this.uiNotificationService.error(
                    this.t('socialSettings.notifications.oneChannelRequired'),
                    this.t('socialSettings.communication.channelPriority')
                );
            }
        }

        if (primary === 'main_chat') {
            this.socialForm.get(telegramFallbackPath)?.setValue(false, { emitEvent: false });
        }
    }

    private mapCommunicationToForm(communication: any): any {
        const source = communication && typeof communication === 'object' ? communication : {};
        const priorityRaw = Array.isArray(source.priority) ? source.priority : [];
        const primary = String(priorityRaw[0] || 'main_chat') === 'telegram' ? 'telegram' : 'main_chat';
        const channels = source.channels && typeof source.channels === 'object' ? source.channels : {};
        const mainCfg = channels.main_chat && typeof channels.main_chat === 'object' ? channels.main_chat : {};
        const telegramCfg = channels.telegram && typeof channels.telegram === 'object' ? channels.telegram : {};
        return {
            primary_channel: primary,
            channels: {
                main_chat: {
                    enabled: mainCfg.enabled !== undefined ? !!mainCfg.enabled : true,
                    allow_fallback: false,
                },
                telegram: {
                    enabled: telegramCfg.enabled !== undefined ? !!telegramCfg.enabled : true,
                    allow_fallback:
                        primary === 'main_chat'
                            ? false
                            : telegramCfg.allow_fallback !== undefined
                              ? !!telegramCfg.allow_fallback
                              : true,
                },
            },
        };
    }

    private mapCommunicationFromForm(formValue: any): any {
        const data = formValue && typeof formValue === 'object' ? formValue : {};
        const primary = String(data.primary_channel || 'main_chat') === 'telegram' ? 'telegram' : 'main_chat';
        const channels = data.channels && typeof data.channels === 'object' ? data.channels : {};
        const mainCfg = channels.main_chat && typeof channels.main_chat === 'object' ? channels.main_chat : {};
        const telegramCfg = channels.telegram && typeof channels.telegram === 'object' ? channels.telegram : {};
        const mainEnabled = mainCfg.enabled !== undefined ? !!mainCfg.enabled : true;
        const telegramEnabled = telegramCfg.enabled !== undefined ? !!telegramCfg.enabled : true;

        return {
            priority: primary === 'telegram' ? ['telegram', 'main_chat'] : ['main_chat', 'telegram'],
            channels: {
                main_chat: {
                    enabled: mainEnabled || !telegramEnabled,
                    allow_fallback: false,
                },
                telegram: {
                    enabled: telegramEnabled || !mainEnabled,
                    allow_fallback: primary === 'main_chat' ? false : !!telegramCfg.allow_fallback,
                },
            },
        };
    }

    private syncAllowedChatIdsTextFromForm(): void {
        const ids = this.socialForm.get('telegram.routing.allowed_chat_ids')?.value;
        if (Array.isArray(ids)) {
            this.allowedChatIdsInput = ids.join(', ');
        } else {
            this.allowedChatIdsInput = '';
        }
    }

    private syncAllowedChatIdsFormFromText(): void {
        const parsed = String(this.allowedChatIdsInput || '')
            .split(',')
            .map((item) => Number(item.trim()))
            .filter((item) => Number.isInteger(item) && item !== 0);
        this.socialForm.get('telegram.routing.allowed_chat_ids')?.setValue(parsed);
    }

    private rebuildOwnerChatOptions(): void {
        const options: UiSelectOption[] = [
            { value: 0, label: this.t('socialSettings.common.notSelected') },
        ];
        for (const peer of this.privateTelegramPeers) {
            options.push({
                value: Number(peer.chat_id),
                label: this.formatPeerLabel(peer),
            });
        }
        this.ownerChatOptions = options;
        this.reflectionTargetOptions = [...options];
    }

    isAllowedChatSelected(chatId: number): boolean {
        const ids = this.socialForm.get('telegram.routing.allowed_chat_ids')?.value;
        if (!Array.isArray(ids)) {
            return false;
        }
        return ids.includes(chatId);
    }

    toggleAllowedChat(chatId: number, checked: boolean): void {
        const control = this.socialForm.get('telegram.routing.allowed_chat_ids');
        const next = this.toggleNumericIdControl(control, chatId, checked);
        this.allowedChatIdsInput = next.join(', ');
    }

    isAllowedPrivateChatSelected(chatId: number): boolean {
        return this.isNumericIdSelected('telegram.write_policy.allowed_private_chat_ids', chatId);
    }

    toggleAllowedPrivateChat(chatId: number, checked: boolean): void {
        const next = this.toggleNumericIdControl(
            this.socialForm.get('telegram.write_policy.allowed_private_chat_ids'),
            chatId,
            checked,
        );
        this.allowedPrivateChatIdsInput = next.join(', ');
    }

    isSandboxChatSelected(chatId: number): boolean {
        return this.isNumericIdSelected('telegram.write_policy.sandbox_chat_ids', chatId);
    }

    toggleSandboxChat(chatId: number, checked: boolean): void {
        const next = this.toggleNumericIdControl(
            this.socialForm.get('telegram.write_policy.sandbox_chat_ids'),
            chatId,
            checked,
        );
        this.sandboxChatIdsInput = next.join(', ');
    }

    isReflectionSourceChatSelected(chatId: number): boolean {
        return this.isNumericIdSelected('telegram.reflection.source_chat_ids', chatId);
    }

    toggleReflectionSourceChat(chatId: number, checked: boolean): void {
        const next = this.toggleNumericIdControl(
            this.socialForm.get('telegram.reflection.source_chat_ids'),
            chatId,
            checked,
        );
        this.reflectionSourceChatIdsInput = next.join(', ');
    }

    isReflectionSourceKindSelected(kind: string): boolean {
        const current = this.socialForm.get('telegram.reflection.source_chat_kinds')?.value;
        return Array.isArray(current) ? current.includes(kind) : false;
    }

    toggleReflectionSourceKind(kind: string, checked: boolean): void {
        this.toggleNumericLikeStringArrayControl(
            this.socialForm.get('telegram.reflection.source_chat_kinds'),
            kind,
            checked,
        );
    }

    formatPeerLabel(peer: TelegramChatPeer): string {
        const kind = String(peer.chat_kind || 'unknown').toUpperCase();
        const unread = Number(peer.unread_count || 0);
        const unreadTag = unread > 0 ? ` • unread:${unread}` : '';
        const username = peer.username ? ` @${peer.username}` : '';
        return `${peer.title}${username} (${kind})${unreadTag}`;
    }

    get privateTelegramPeers(): TelegramChatPeer[] {
        return this.telegramPeers.filter((peer) => String(peer.chat_kind || '').toLowerCase() === 'private');
    }

    get publicTelegramPeers(): TelegramChatPeer[] {
        return this.telegramPeers.filter((peer) => {
            const kind = String(peer.chat_kind || '').toLowerCase();
            return kind === 'group' || kind === 'channel';
        });
    }

    get reflectionSourceSelectionCount(): number {
        const ids = this.socialForm.get('telegram.reflection.source_chat_ids')?.value;
        return Array.isArray(ids) ? ids.length : 0;
    }

    get isUsingAutomaticReflectionSources(): boolean {
        return this.reflectionSourceSelectionCount === 0;
    }

    private syncWritePolicyTextFromForm(): void {
        const allowedPrivate = this.socialForm.get('telegram.write_policy.allowed_private_chat_ids')?.value;
        const sandbox = this.socialForm.get('telegram.write_policy.sandbox_chat_ids')?.value;
        this.allowedPrivateChatIdsInput = Array.isArray(allowedPrivate) ? allowedPrivate.join(', ') : '';
        this.sandboxChatIdsInput = Array.isArray(sandbox) ? sandbox.join(', ') : '';
    }

    private syncWritePolicyFormFromText(): void {
        this.socialForm
            .get('telegram.write_policy.allowed_private_chat_ids')
            ?.setValue(this.parseNumericIdList(this.allowedPrivateChatIdsInput));
        this.socialForm
            .get('telegram.write_policy.sandbox_chat_ids')
            ?.setValue(this.parseNumericIdList(this.sandboxChatIdsInput));
    }

    private syncReflectionSourceChatIdsTextFromForm(): void {
        const ids = this.socialForm.get('telegram.reflection.source_chat_ids')?.value;
        this.reflectionSourceChatIdsInput = Array.isArray(ids) ? ids.join(', ') : '';
    }

    private syncReflectionSourceChatIdsFormFromText(): void {
        this.socialForm
            .get('telegram.reflection.source_chat_ids')
            ?.setValue(this.parseNumericIdList(this.reflectionSourceChatIdsInput));
    }

    private applyLocalizedDefaults(): void {
        this.applyLocalizedDefaultToControl(
            'telegram.channels.reflection_instruction',
            'socialSettings.channels.reflectionInstructionDefault',
            this.legacyChannelReflectionInstruction,
        );
        this.applyLocalizedDefaultToControl(
            'telegram.reflection.prompt',
            'socialSettings.reflection.promptDefault',
            this.legacyReflectionPrompt,
        );
        this.applyLocalizedDefaultToControl(
            'telegram.initiative.prompt_template',
            'socialSettings.initiative.promptTemplateDefault',
            this.legacyInitiativePrompt,
        );
        this.applyLocalizedDefaultToControl(
            'telegram.autonomous_inbox.prompt_template',
            'socialSettings.autonomousInbox.promptTemplateDefault',
            this.legacyAutonomousInboxPrompt,
        );
    }

    private applyLocalizedDefaultToControl(path: string, translationKey: string, legacyDefault: string): void {
        const control = this.socialForm.get(path);
        if (!control) {
            return;
        }
        const current = String(control.value ?? '').trim();
        if (current && current !== legacyDefault) {
            return;
        }
        control.setValue(this.t(translationKey), { emitEvent: false });
    }

    private parseNumericIdList(rawValue: string): number[] {
        return String(rawValue || '')
            .split(',')
            .map((item) => Number(item.trim()))
            .filter((item) => Number.isInteger(item) && item !== 0);
    }

    private resolveReflectionProbeSourceChatId(): number | undefined {
        const selectedIds = this.socialForm.get('telegram.reflection.source_chat_ids')?.value;
        if (Array.isArray(selectedIds) && selectedIds.length > 0) {
            const id = Number(selectedIds[0]);
            if (Number.isInteger(id) && id !== 0) {
                return id;
            }
        }
        const firstPublic = this.publicTelegramPeers[0];
        if (firstPublic && Number.isInteger(Number(firstPublic.chat_id)) && Number(firstPublic.chat_id) !== 0) {
            return Number(firstPublic.chat_id);
        }
        return undefined;
    }

    private resolveImageTestTargetChatId(): number | undefined {
        const reflectionTarget = Number(this.socialForm.get('telegram.reflection.target_chat_id')?.value || 0);
        if (Number.isInteger(reflectionTarget) && reflectionTarget !== 0) {
            return reflectionTarget;
        }
        const ownerTarget = Number(this.socialForm.get('telegram.lockdown.owner_chat_id')?.value || 0);
        if (Number.isInteger(ownerTarget) && ownerTarget !== 0) {
            return ownerTarget;
        }
        return undefined;
    }

    private isNumericIdSelected(path: string, chatId: number): boolean {
        const ids = this.socialForm.get(path)?.value;
        return Array.isArray(ids) ? ids.includes(chatId) : false;
    }

    private toggleNumericIdControl(control: any, id: number, checked: boolean): number[] {
        const current = Array.isArray(control?.value) ? [...control.value] : [];
        const next = checked
            ? Array.from(new Set([...current, id]))
            : current.filter((item) => Number(item) !== Number(id));
        control?.setValue(next);
        return next;
    }

    private toggleNumericLikeStringArrayControl(control: any, value: string, checked: boolean): string[] {
        const current = Array.isArray(control?.value) ? [...control.value].map((item) => String(item)) : [];
        const normalized = String(value || '').trim();
        const next = checked
            ? Array.from(new Set([...current, normalized]))
            : current.filter((item) => item !== normalized);
        control?.setValue(next);
        return next;
    }

    private deepClone<T>(value: T): T {
        return JSON.parse(JSON.stringify(value ?? {}));
    }

    private deepMerge(target: any, source: any): any {
        if (!source || typeof source !== 'object' || Array.isArray(source)) {
            return source !== undefined ? source : target;
        }
        const out = target && typeof target === 'object' && !Array.isArray(target) ? target : {};
        Object.keys(source).forEach((key) => {
            const sourceValue = source[key];
            if (Array.isArray(sourceValue)) {
                out[key] = [...sourceValue];
                return;
            }
            if (sourceValue && typeof sourceValue === 'object') {
                out[key] = this.deepMerge(out[key], sourceValue);
                return;
            }
            out[key] = sourceValue;
        });
        return out;
    }
}
