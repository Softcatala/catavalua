import { Entity, PrimaryGeneratedColumn, Column, ManyToOne, JoinColumn } from 'typeorm';
import { Clip } from './clip.entity';

@Entity('transcriptions')
export class Transcription {
  @PrimaryGeneratedColumn()
  id: number;

  @Column({ name: 'clip_id' })
  clipId: string;

  @ManyToOne(() => Clip, (c) => c.transcriptions)
  @JoinColumn({ name: 'clip_id' })
  clip: Clip;

  // origin: 'claude', 'gemini', 'human', 'candidate_1', 'candidate_2'
  @Column()
  origin: string;

  @Column('text')
  text: string;

  // JSON string for model-detected metadata (e.g. {"gender": "female", "dialect": "valencian"})
  @Column('text', { nullable: true })
  metadata: string;

  @Column({ name: 'created_at', nullable: true })
  createdAt: string;
}
