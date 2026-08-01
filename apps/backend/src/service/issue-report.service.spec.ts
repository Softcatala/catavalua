import { Test } from '@nestjs/testing';
import { TypeOrmModule, getRepositoryToken } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { IssueReportService } from './issue-report.service';
import { IssueReport } from '../domain/issue-report.entity';
import { Clip } from '../domain/clip.entity';
import { Transcription } from '../domain/transcription.entity';
import { Vote } from '../domain/vote.entity';
import { MetricsService } from '../observability/metrics.service';

describe('IssueReportService', () => {
  let service: IssueReportService;
  let repo: Repository<IssueReport>;

  beforeEach(async () => {
    const module = await Test.createTestingModule({
      imports: [
        TypeOrmModule.forRoot({
          type: 'sqlite',
          database: ':memory:',
          // IssueReport's @ManyToOne(Clip) needs the full entity graph registered —
          // Clip's own @OneToMany(Transcription)/@OneToMany(Vote) relations otherwise
          // fail metadata build in a way @nestjs/typeorm's retry logic misreports as
          // "sqlite3 not installed" (see vote.service.spec.ts for the same gotcha).
          entities: [IssueReport, Clip, Transcription, Vote],
          synchronize: true,
        }),
        TypeOrmModule.forFeature([IssueReport, Clip]),
      ],
      providers: [IssueReportService, MetricsService],
    }).compile();

    service = module.get(IssueReportService);
    repo = module.get(getRepositoryToken(IssueReport));

    const clips: Repository<Clip> = module.get(getRepositoryToken(Clip));
    await clips.save(clips.create({ clipId: 'clip-1' }));
  });

  it('creates a report as open, snapshotting the dimension and its shown value', async () => {
    const report = await service.create({
      clipId: 'clip-1',
      dimension: 'transcription',
      dimensionValue: 'hola bon dia',
      message: 'The transcription is missing the last word.',
      username: 'alice',
    });

    expect(report).toMatchObject({
      clipId: 'clip-1',
      dimension: 'transcription',
      dimensionValue: 'hola bon dia',
      status: 'open',
      username: 'alice',
    });
    expect(report.id).toBeDefined();
    expect(report.createdAt).toBeDefined();
  });

  it('rejects a message over 1000 characters at the database layer', async () => {
    const tooLong = 'x'.repeat(1001);
    await expect(
      repo.save(repo.create({
        clipId: 'clip-1',
        dimension: 'gender',
        message: tooLong,
        username: 'alice',
        status: 'open',
        createdAt: new Date().toISOString(),
      })),
    ).rejects.toThrow();
  });

  it('filters by status, and returns everything when no status is given', async () => {
    const a = await service.create({ clipId: 'clip-1', dimension: 'gender', message: 'wrong gender', username: 'alice' });
    await service.create({ clipId: 'clip-1', dimension: 'dialect', message: 'wrong dialect', username: 'bob' });
    await service.updateStatus(a.id, 'done');

    const open = await service.findByStatus('open');
    const done = await service.findByStatus('done');
    const all = await service.findByStatus();

    expect(open).toHaveLength(1);
    expect(open[0].message).toBe('wrong dialect');
    expect(done).toHaveLength(1);
    expect(done[0].id).toBe(a.id);
    expect(all).toHaveLength(2);
  });

  it('updates status in place', async () => {
    const report = await service.create({ clipId: 'clip-1', dimension: 'transcription', message: 'garbled audio', username: 'alice' });
    expect(report.status).toBe('open');

    const updated = await service.updateStatus(report.id, 'done');
    expect(updated.status).toBe('done');

    const reloaded = await repo.findOne({ where: { id: report.id } });
    expect(reloaded?.status).toBe('done');
  });

  it('throws when updating the status of a nonexistent report', async () => {
    await expect(service.updateStatus(999, 'done')).rejects.toThrow();
  });
});
