import { Entity, PrimaryGeneratedColumn, Column, ManyToOne, JoinColumn, Unique } from 'typeorm';
import { Clip } from './clip.entity';

// dimension: 'transcription' | 'gender' | (any future metadata field)
// For 'transcription' dimension, target_id is the transcription id (as string)
// For other dimensions, target_id is the value being voted on (e.g. 'female')

@Entity('votes')
@Unique(['clipId', 'dimension', 'username'])
export class Vote {
  @PrimaryGeneratedColumn()
  id: number;

  @Column({ name: 'clip_id' })
  clipId: string;

  @ManyToOne(() => Clip, (c) => c.votes)
  @JoinColumn({ name: 'clip_id' })
  clip: Clip;

  @Column()
  dimension: string;

  @Column({ name: 'target_id', nullable: true })
  targetId: string;

  @Column()
  username: string;

  @Column('integer')
  value: number; // +1 correct, -1 incorrect

  @Column({ name: 'created_at', nullable: true })
  createdAt: string;
}
