import {
  Controller,
  Get,
  Post,
  Delete,
  Param,
  Query,
  Body,
  ParseIntPipe,
  DefaultValuePipe,
  BadRequestException,
  UseGuards,
} from '@nestjs/common';
import { ClipService, IRRELEVANT_REASONS, IrrelevantReason } from '../service/clip.service';
import { TranscriptionService } from '../service/transcription.service';
import { ApiKeyGuard } from './api-key.guard';
import { IsString, IsOptional, IsNumber, IsNotEmpty } from 'class-validator';
import { Type } from 'class-transformer';

class UpsertClipDto {
  @IsString() @IsNotEmpty() clipId: string;
  @IsOptional() @IsString() sourceId?: string;
  @IsOptional() @IsNumber() @Type(() => Number) duration?: number;
  @IsOptional() @IsNumber() @Type(() => Number) start?: number;
  @IsOptional() @IsNumber() @Type(() => Number) end?: number;
  @IsOptional() @IsString() gender?: string;
  @IsOptional() @IsString() candidate1?: string;
  @IsOptional() @IsString() candidate2?: string;
  @IsOptional() @IsString() ytUrl?: string;
  @IsOptional() @IsString() license?: string;
  @IsOptional() @IsString() detectedDialect?: string;
  @IsOptional() @IsString() detectedLanguage?: string;
  @IsOptional() isRelevant?: boolean;
}

class UpdateTarIndexDto {
  @IsNumber() @Type(() => Number) tarFile: number;
  @IsNumber() @Type(() => Number) tarOffset: number;
  @IsNumber() @Type(() => Number) tarSize: number;
}

@Controller('clips')
export class ClipController {
  constructor(
    private readonly clipService: ClipService,
    private readonly transcriptionService: TranscriptionService,
  ) {}

  @Get()
  async list(
    @Query('search') search = '',
    @Query('page', new DefaultValuePipe(1), ParseIntPipe) page: number,
    @Query('limit', new DefaultValuePipe(20), ParseIntPipe) limit: number,
  ) {
    return this.clipService.list(search, page, Math.min(limit, 100));
  }

  @Get(':id')
  async findOne(@Param('id') id: string) {
    return this.clipService.findOne(id);
  }

  @Get(':id/transcriptions')
  async transcriptions(@Param('id') id: string) {
    return this.transcriptionService.findByClip(id);
  }

  @UseGuards(ApiKeyGuard)
  @Post()
  async upsert(@Body() dto: UpsertClipDto) {
    return this.clipService.upsert(dto as any);
  }

  @UseGuards(ApiKeyGuard)
  @Post(':id/tar-index')
  async updateTarIndex(@Param('id') id: string, @Body() dto: UpdateTarIndexDto) {
    await this.clipService.updateTarIndex(id, dto.tarFile, dto.tarOffset, dto.tarSize);
    return { ok: true };
  }

  @Post(':id/flag-irrelevant')
  async flagIrrelevant(
    @Param('id') id: string,
    @Query('username') username: string,
    @Query('reason') reason: string = 'not_catalan',
  ) {
    if (!username) throw new BadRequestException('username required');
    if (!IRRELEVANT_REASONS.includes(reason as IrrelevantReason)) {
      throw new BadRequestException(`invalid reason: ${reason}`);
    }
    await this.clipService.flagIrrelevant(id, username, reason as IrrelevantReason);
    return { ok: true };
  }

  @UseGuards(ApiKeyGuard)
  @Delete(':id')
  async remove(@Param('id') id: string) {
    await this.clipService.remove(id);
    return { ok: true };
  }
}
