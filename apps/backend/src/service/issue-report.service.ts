import { Injectable, NotFoundException } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { IssueReport, IssueReportStatus } from '../domain/issue-report.entity';
import { MetricsService } from '../observability/metrics.service';

@Injectable()
export class IssueReportService {
  constructor(
    @InjectRepository(IssueReport) private readonly repo: Repository<IssueReport>,
    private readonly metrics: MetricsService,
  ) {}

  async create(data: {
    clipId: string;
    dimension: string;
    dimensionValue?: string;
    message: string;
    username: string;
  }): Promise<IssueReport> {
    const report = this.repo.create({
      ...data,
      status: 'open',
      createdAt: new Date().toISOString(),
    });
    const saved = await this.repo.save(report);
    this.metrics.issueReportsTotal.inc({ dimension: data.dimension });
    return saved;
  }

  async findByStatus(status?: IssueReportStatus): Promise<IssueReport[]> {
    return this.repo.find({
      where: status ? { status } : {},
      order: { id: 'DESC' },
    });
  }

  async updateStatus(id: number, status: IssueReportStatus): Promise<IssueReport> {
    const report = await this.repo.findOne({ where: { id } });
    if (!report) throw new NotFoundException(`Issue report ${id} not found`);
    report.status = status;
    return this.repo.save(report);
  }
}
