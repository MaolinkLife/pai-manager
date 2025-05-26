import { Component, OnInit } from '@angular/core';
import { ApiService } from '../../core/services/api.service';
import { Message } from '../../core/models/message.model';
import { FormControl } from '@angular/forms';

@Component({
    selector: 'app-chat',
    templateUrl: './chat.component.html',
    styleUrls: ['./chat.component.less']
})
export class ChatComponent implements OnInit {
    chatInput = new FormControl('');
    chatHistory: Message[] = [];
    loading = false;

    constructor(private apiService: ApiService) { }

    ngOnInit(): void {
    }

    sendMessage() {
        const trimmed = this.chatInput.value?.trim();
        if (!trimmed) return;

        const userMessage: Message = { role: 'user', content: trimmed };
        this.chatHistory.push(userMessage);
        this.chatInput.setValue('');
        this.loading = true;

        const message = {
            "history": [...this.chatHistory],
            "temp_level": 1,
            "max_tokens": 512
        }
        this.apiService.sendMessage$(message).subscribe({
            next: (res) => {
                this.chatHistory.push({ role: 'assistant', content: res.response });
                this.loading = false;
            },
            error: (err) => {
                this.chatHistory.push({
                    role: 'assistant',
                    content: '[Ошибка получения ответа]',
                });
                this.loading = false;
                console.error(err);
            },
        });
    }
}
