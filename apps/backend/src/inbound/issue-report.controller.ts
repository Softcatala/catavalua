import { Controller, Get, Post, Patch, Body, Param, Query, ParseIntPipe, BadRequestException } from '@nestjs/common';
import { IssueReportService } from '../service/issue-report.service';
import { IsString, IsNotEmpty, IsOptional, IsIn, MaxLength } from 'class-validator';
import { IssueReportStatus } from '../domain/issue-report.entity';

const STATUSES: IssueReportStatus[] = ['open', 'done'];

class CreateIssueReportDto {
  @IsString() @IsNotEmpty() clipId: string;
  @IsString() @IsIn(['transcription', 'gender', 'dialect']) dimension: string;
  @IsOptional() @IsString() dimensionValue?: string;
  @IsString() @IsNotEmpty() @MaxLength(1000) message: string;
  @IsString() @IsNotEmpty() username: string;
}

class UpdateIssueReportStatusDto {
  @IsString() @IsIn(STATUSES) status: IssueReportStatus;
}

@Controller('issue-reports')
export class IssueReportController {
  constructor(private readonly service: IssueReportService) {}

  @Post()
  async create(@Body() dto: CreateIssueReportDto) {
    return this.service.create(dto);
  }

  @Get()
  async list(@Query('status') status?: string) {
    if (status && !STATUSES.includes(status as IssueReportStatus)) {
      throw new BadRequestException(`status must be one of: ${STATUSES.join(', ')}`);
    }
    return this.service.findByStatus(status as IssueReportStatus | undefined);
  }

  @Patch(':id/status')
  async updateStatus(@Param('id', ParseIntPipe) id: number, @Body() dto: UpdateIssueReportStatusDto) {
    return this.service.updateStatus(id, dto.status);
  }
}
