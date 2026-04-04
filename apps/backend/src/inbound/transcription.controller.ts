import { Controller, Post, Body } from '@nestjs/common';
import { TranscriptionService } from '../service/transcription.service';
import { IsString, IsNotEmpty, IsOptional } from 'class-validator';

class CreateTranscriptionDto {
  @IsString() @IsNotEmpty() clipId: string;
  @IsString() @IsNotEmpty() origin: string;
  @IsString() @IsNotEmpty() text: string;
  @IsOptional() @IsString() metadata?: string;
}

@Controller('transcriptions')
export class TranscriptionController {
  constructor(private readonly service: TranscriptionService) {}

  @Post()
  async create(@Body() dto: CreateTranscriptionDto) {
    return this.service.create(dto);
  }
}
