import { CommonModule } from '@angular/common';
import { NgModule } from '@angular/core';
import { SharedModule } from '../../shared/shared.module';
import { LibraryRoutingModule } from './library-routing.module';
import { LibraryComponent } from './library.component';

@NgModule({
    declarations: [LibraryComponent],
    imports: [CommonModule, SharedModule, LibraryRoutingModule],
})
export class LibraryModule {}
