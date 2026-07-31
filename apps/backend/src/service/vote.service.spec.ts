import { Test } from '@nestjs/testing';
import { TypeOrmModule, getRepositoryToken } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { VoteService } from './vote.service';
import { Vote } from '../domain/vote.entity';
import { Clip } from '../domain/clip.entity';
import { Transcription } from '../domain/transcription.entity';

describe('VoteService', () => {
  let service: VoteService;
  let repo: Repository<Vote>;

  beforeEach(async () => {
    const module = await Test.createTestingModule({
      imports: [
        TypeOrmModule.forRoot({
          type: 'sqlite',
          database: ':memory:',
          // Vote's @ManyToOne(Clip) needs the full entity graph registered,
          // otherwise TypeORM's metadata build fails in a way that
          // @nestjs/typeorm's retry logic reports as a misleading
          // "sqlite3 not installed" error.
          entities: [Vote, Clip, Transcription],
          synchronize: true,
        }),
        TypeOrmModule.forFeature([Vote, Clip]),
      ],
      providers: [VoteService],
    }).compile();

    service = module.get(VoteService);
    repo = module.get(getRepositoryToken(Vote));

    // Vote.clipId is a real FK against clips, so seed the clips these tests vote on.
    const clips: Repository<Clip> = module.get(getRepositoryToken(Clip));
    await clips.save(clips.create({ clipId: 'clip-1', gender: 'female', duration: 3600 })); // 1h
    await clips.save(clips.create({ clipId: 'clip-2', detectedDialect: 'central', duration: 1800 })); // 0.5h
    // Never voted on — should still count toward totalHours but not evaluated/golden hours.
    await clips.save(clips.create({ clipId: 'clip-3', duration: 3600 })); // 1h
  });

  it('lets a user hold independent votes on competing candidates within one dimension', async () => {
    // Downvoting the current gender and upvoting the proposed alternative used to
    // collide on the old (clipId, dimension, username) unique constraint.
    await service.cast({ clipId: 'clip-1', dimension: 'gender', targetId: 'female', username: 'alice', value: -1 });
    await service.cast({ clipId: 'clip-1', dimension: 'gender', targetId: 'male', username: 'alice', value: 1 });

    const rows = await repo.find({ where: { clipId: 'clip-1', username: 'alice' } });
    expect(rows).toHaveLength(2);
    expect(rows.find((r) => r.targetId === 'female')?.value).toBe(-1);
    expect(rows.find((r) => r.targetId === 'male')?.value).toBe(1);
  });

  it('upserts in place when the same user votes again on the same target', async () => {
    await service.cast({ clipId: 'clip-1', dimension: 'gender', targetId: 'male', username: 'alice', value: 1 });
    await service.cast({ clipId: 'clip-1', dimension: 'gender', targetId: 'male', username: 'alice', value: -1 });

    const rows = await repo.find({ where: { clipId: 'clip-1', username: 'alice', targetId: 'male' } });
    expect(rows).toHaveLength(1);
    expect(rows[0].value).toBe(-1);
  });

  it('raises a competing gender candidate to golden once two evaluators confirm it', async () => {
    // dave downvotes the original 'female' label and raises 'male' as the alternative
    await service.cast({ clipId: 'clip-1', dimension: 'gender', targetId: 'female', username: 'dave', value: -1 });
    await service.cast({ clipId: 'clip-1', dimension: 'gender', targetId: 'male', username: 'dave', value: 1 });
    // erin independently confirms 'male'
    await service.cast({ clipId: 'clip-1', dimension: 'gender', targetId: 'male', username: 'erin', value: 1 });

    const summary = await service.summaryForClip('clip-1');
    const male = summary.find((s) => s.targetId === 'male');
    const female = summary.find((s) => s.targetId === 'female');

    expect(male).toMatchObject({ netVotes: 2, isGolden: true });
    expect(female).toMatchObject({ netVotes: -1, isGolden: false });
  });

  it('supports a dialect candidate chosen from a picker the same way', async () => {
    await service.cast({ clipId: 'clip-2', dimension: 'dialect', targetId: 'central', username: 'alice', value: -1 });
    await service.cast({ clipId: 'clip-2', dimension: 'dialect', targetId: 'valencian', username: 'alice', value: 1 });
    await service.cast({ clipId: 'clip-2', dimension: 'dialect', targetId: 'valencian', username: 'bob', value: 1 });

    const summary = await service.summaryForClip('clip-2');
    const valencian = summary.find((s) => s.targetId === 'valencian');

    expect(valencian).toMatchObject({ netVotes: 2, isGolden: true });
  });

  it('excludes scripts/infer_dialect.py\'s bulk-vote username from stats but still counts it in summaryForClip', async () => {
    // Bot suggests a dialect on clip-2 — nobody else has weighed in yet.
    await service.cast({ clipId: 'clip-2', dimension: 'dialect', targetId: 'valencian', username: 'derivat-de-poblacio', value: 1 });
    // Real evaluator does independent work on clip-1.
    await service.cast({ clipId: 'clip-1', dimension: 'gender', targetId: 'male', username: 'alice', value: 1 });

    const stats = await service.stats();
    const dialect = stats.dimensions.find((d) => d.dimension === 'dialect');
    const gender = stats.dimensions.find((d) => d.dimension === 'gender');

    // The bot-only vote shouldn't make clip-2 look human-evaluated in stats...
    expect(dialect).toBeUndefined();
    expect(gender).toMatchObject({ evaluated: 1, golden: 0 });

    // ...but it still surfaces as a real candidate for a human to confirm/reject.
    const summary = await service.summaryForClip('clip-2');
    expect(summary.find((s) => s.targetId === 'valencian')).toMatchObject({ netVotes: 1, isGolden: false });
  });

  it('weights evaluated/golden hours by clip duration, and totalHours covers every clip regardless of votes', async () => {
    // clip-1 (1h): reaches golden gender.
    await service.cast({ clipId: 'clip-1', dimension: 'gender', targetId: 'male', username: 'dave', value: 1 });
    await service.cast({ clipId: 'clip-1', dimension: 'gender', targetId: 'male', username: 'erin', value: 1 });
    // clip-2 (0.5h): evaluated but not yet golden.
    await service.cast({ clipId: 'clip-2', dimension: 'gender', targetId: 'female', username: 'alice', value: 1 });
    // clip-3 (1h) is never voted on.

    const stats = await service.stats();
    const gender = stats.dimensions.find((d) => d.dimension === 'gender');

    expect(gender).toMatchObject({ evaluated: 2, golden: 1, evaluatedHours: 1.5, goldenHours: 1 });
    // clip-1 + clip-2 + clip-3 = 1 + 0.5 + 1 = 2.5h, including the never-voted-on clip.
    expect(stats.totalHours).toBe(2.5);
  });
});
